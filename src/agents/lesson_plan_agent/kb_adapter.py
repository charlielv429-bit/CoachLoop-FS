"""知识库候选检索与证据分级；检索分数、出处标记均不等于事实核验。

A: 正文、出处一致，且有人工核验记录直接支持当前陈述。
B: 可定位的候选正文，尚未确认支持关系。C: 无效或不可定位的片段。
只有 A 可形成正式教学依据。人工核验记录须由可信的人审流程提供，
本模块不调用 LLM、不从检索内容或分数生成核验记录。
"""
import math
import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from coze_coding_dev_sdk import Config, KnowledgeClient

_SRC_MARKER = re.compile(
    r"【原文出处】\s*(?P<file>[^｜|\n]+?)\s*[｜|]\s*原PDF第(?P<page>\d+)页"
)
_MIN_SCORE = 0.5
DEFAULT_STATEMENT = "体育与健康课程核心素养包括运动能力、健康行为和体育品德。"
DEFAULT_QUERIES = [
    "体育与健康学科核心素养包括什么？",
    "运动能力在体育教学中如何体现？",
    "健康行为与体育品德对应哪些课程目标？",
]


class EvidenceGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class HumanVerification(BaseModel):
    """可信人审流程提供的记录；绑定原始全文、出处与被支持的确切陈述。

    这是人审结果的输入契约，不是身份认证接口。不得从知识库片段自动构造。
    """
    model_config = ConfigDict(str_strip_whitespace=True)
    reviewer: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    page: str = Field(pattern=r"^[1-9]\d*$")
    content: str = Field(min_length=1)
    supported_statement: str = Field(min_length=1)
    supports_statement: bool


class KBHit(BaseModel):
    """检索候选，不代表已核实；新增人审字段默认空以兼容旧调用。"""
    query: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    source_file: str = Field(..., min_length=1)
    page: str = Field(..., min_length=1)
    score: float
    human_verification: Optional[HumanVerification] = None


def _parse_citation(content: str) -> Optional[tuple]:
    markers = list(_SRC_MARKER.finditer(content or ""))
    if len(markers) != 1 or int(markers[0].group("page")) <= 0:
        return None
    return markers[0].group("file").strip(), markers[0].group("page")


def _is_image_chunk(content: str) -> bool:
    # 标记前后、任意 alt 文本的图片块均不可当作正文；保守降级。
    return bool(re.search(r"!\[[^\]]*\]\s*\(|<img\b", content or "", re.I))


def _has_body(content: str) -> bool:
    """保守筛选正文候选；通过本筛选仍不代表支持某个论断。"""
    body = _SRC_MARKER.sub("", content or "")
    body = re.sub(r"[｜|]?\s*文件\s*p\d+", "", body).strip()
    if _is_image_chunk(body):
        return False
    if re.search(r"目\s*录|table\s+of\s+contents|[.…·]{2,}\s*\d+", body, re.I):
        return False
    # 标题/章节名和只有来源的片段不能成为正文证据。
    return len(body) >= 20 and bool(re.search(r"[。！？.!?；;]", body))


def classify_evidence(entry, statement: str = DEFAULT_STATEMENT,
                      min_score: float = _MIN_SCORE) -> EvidenceGrade:
    """分级不可由输入的 grade 或 LLM 判断覆盖；A级必须绑定可信人审记录。"""
    if not isinstance(entry, KBHit):
        return EvidenceGrade.C
    parsed = _parse_citation(entry.content)
    if (parsed != (entry.source_file, entry.page)
            or not math.isfinite(entry.score) or entry.score < min_score
            or not _has_body(entry.content)):
        return EvidenceGrade.C
    review = entry.human_verification
    if (review is not None and review.supports_statement
            and review.supported_statement == statement
            and review.source_file == entry.source_file and review.page == entry.page
            and review.content == entry.content):
        return EvidenceGrade.A
    return EvidenceGrade.B


def retrieve_kb(queries: Optional[List[str]] = None, top_k: int = 6,
                min_score: float = _MIN_SCORE, *, client=None,
                client_factory=None, config_factory=None) -> dict:
    """保留 ok/hits，另加 status/errors 以区分无命中、配置失败与检索失败。

    client 可直接注入以完全避免凭据和网络；默认初始化延迟到调用时。
    检索只返回 B 级正文候选，绝不从远端返回值读取人工核验记录。
    errors 只记录错误类型，不暴露凭据或原始服务异常内容。
    """
    qs = queries if queries else list(DEFAULT_QUERIES)
    result, errors = {}, []
    if client is None:
        try:
            config = (config_factory or Config)()
        except Exception as exc:
            return {"ok": False, "hits": {}, "status": "configuration_error",
                    "errors": [{"stage": "configuration", "type": type(exc).__name__}]}
        try:
            client = (client_factory or KnowledgeClient)(config=config)
        except Exception as exc:
            return {"ok": False, "hits": {}, "status": "client_error",
                    "errors": [{"stage": "client", "type": type(exc).__name__}]}
    for q in qs:
        hits = []
        try:
            resp = client.search(query=q, top_k=top_k, min_score=0.0)
            chunks = getattr(resp, "chunks", None) or []
        except Exception as exc:
            errors.append({"stage": "search", "type": type(exc).__name__})
            chunks = []
        for c in chunks:
            try:
                content = c.content or ""
                parsed = _parse_citation(content)
                if parsed is None:
                    continue
                hit = KBHit(query=q, content=content, source_file=parsed[0],
                            page=parsed[1], score=getattr(c, "score", 0.0) or 0.0)
                if classify_evidence(hit, min_score=min_score) is EvidenceGrade.B:
                    hits.append(hit)
            except (AttributeError, TypeError, ValueError, ValidationError):
                continue  # 单条坏数据不影响其余结果
        result[q] = hits
    ok = any(result.values())
    status = "partial" if errors and ok else "search_error" if errors else "ok" if ok else "no_evidence"
    return {"ok": ok, "hits": result, "status": status, "errors": errors}
