"""教案生成 Agent —— 最小知识库检索适配器（任务2A）。

仅封装一次真实检索：调用 Coze 知识库语义搜索，且**只把带【原文出处】来源标记、
非图像块(png)的文本命中视为可核验**，产出结构化引用（文件 | 原PDF第N页）。

不可核验情形一律返回空（不虚构引用）：
- 知识库返回图像块（content 以 `![img](...)` 开头，无文字）；
- 无【原文出处】来源标记的内容（如纯标题、平台分割碎片）；
- SDK 初始化/调用异常。
"""
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from coze_coding_dev_sdk import Config, KnowledgeClient

# 来源标记：例如 【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6
_SRC_MARKER = re.compile(
    r"【原文出处】\s*(?P<file>[^｜|]+?)\s*[｜|]\s*原PDF第(?P<page>\d+)页"
)
# 阈值：低于该相似度的命中视为弱相关/噪声，不纳入（可配置）
_MIN_SCORE = 0.5

# 使用教案时实际检索的问题（供 CLI/集成默认调用）
DEFAULT_QUERIES = [
    "体育与健康学科核心素养包括什么？",
    "运动能力在体育教学中如何体现？",
    "健康行为与体育品德对应哪些课程目标？",
]


class KBHit(BaseModel):
    """一条可核验的知识库命中（含来源页码，可回溯）。"""

    query: str = Field(..., min_length=1, description="触发的检索问题")
    content: str = Field(..., min_length=1, description="命中文本")
    source_file: str = Field(..., min_length=1, description="来源文件名称")
    page: str = Field(..., min_length=1, description="原PDF页码")
    score: float = Field(..., description="相似度得分")


def _parse_citation(content: str) -> tuple:
    """从内容中提取 (文件, 页码)；无可信来源标记返回 None。"""
    m = _SRC_MARKER.search(content or "")
    if not m:
        return None
    return (m.group("file").strip(), m.group("page"))


def _is_image_chunk(content: str) -> bool:
    c = (content or "").lstrip()
    return c.startswith("![img]") or c.startswith("![](http")


def retrieve_kb(
    queries: Optional[List[str]] = None,
    top_k: int = 6,
    min_score: float = _MIN_SCORE,
) -> dict:
    """查询知识库，返回 {ok, hits:{query: [KBHit, ...]}}。

    仅返回可核验（有来源标记、非图像块、且 score ≥ min_score）的命中；
    任一异常/不可核验都安全降级为空，绝不虚构引用。
    """
    qs = queries if queries else list(DEFAULT_QUERIES)
    result: dict = {}
    ok = False
    try:
        client = KnowledgeClient(config=Config())
    except Exception:
        return {"ok": False, "hits": {}}

    for q in qs:
        hits: List[KBHit] = []
        try:
            resp = client.search(query=q, top_k=top_k, min_score=0.0)
            chunks = getattr(resp, "chunks", None) or []
        except Exception:
            chunks = []
        for c in chunks:
            content = c.content or ""
            if _is_image_chunk(content):
                continue
            parsed = _parse_citation(content)
            if parsed is None:
                continue  # 无来源标记：不可核验，跳过
            src_file, page = parsed
            score = float(getattr(c, "score", 0.0) or 0.0)
            if score < min_score:
                continue
            hits.append(
                KBHit(query=q, content=content, source_file=src_file, page=page, score=score)
            )
            ok = True
        result[q] = hits
    return {"ok": ok, "hits": result}