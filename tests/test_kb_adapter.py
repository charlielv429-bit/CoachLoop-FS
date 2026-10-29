"""知识库候选、人审证据分级与离线依赖隔离回归测试。

带出处、达分数阈值仅产生候选正文；A 级还须人工核验记录绑定
来源、全文和当前陈述。目录、标题、图像等不得成为正式教学依据。
所有 SDK 行为均注入或模拟，不需要真实凭据和网络。
"""
import json
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents.lesson_plan_agent import kb_adapter  # noqa: E402
from agents.lesson_plan_agent.generate_draft import (  # noqa: E402
    LessonPlanDraftInput,
    _is_verified_kb_entry,
    build_draft,
    draft_to_json,
)
from agents.lesson_plan_agent.kb_adapter import (KBHit, HumanVerification, EvidenceGrade,
    DEFAULT_STATEMENT, classify_evidence, _parse_citation, _is_image_chunk)  # noqa: E402
from agents.lesson_plan_agent.schemas import EvidenceSource  # noqa: E402


def _inp(**kw):
    base = dict(audience="小学三年级", student_count=20, skill_level="初学者",
                theme="冰上双足滑行与身体姿态控制",
                conditions="室内冰场，每人一副冰鞋，教练1名，教师1名",
                total_minutes=45, group_active_min=36.0, individual_active_min=25.0, avg_hr=135.0)
    base.update(kw)
    return LessonPlanDraftInput(**base)


def _marked_hit(query="体育与健康学科核心素养包括什么？", content=None, score=0.62):
    hit = KBHit(
        query=query,
        content=content or "【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6  体育与健康课程核心素养包括运动能力、健康行为和体育品德。",
        source_file="Part1A_Core_Health.pdf",
        page="6",
        score=score,
    )
    hit.human_verification = HumanVerification(
        reviewer="测试人工审核员", source_file=hit.source_file, page=hit.page,
        content=hit.content, supported_statement=DEFAULT_STATEMENT, supports_statement=True,
    )
    return hit


# ---- 适配器：来源标记/图像块识别 ----
def test_parse_citation_from_marker():
    parsed = _parse_citation("前文 【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6  后文")
    assert parsed == ("Part1A_Core_Health.pdf", "6")


def test_parse_citation_none_without_marker():
    assert _parse_citation("体育与健康课程标准（无来源标记）") is None


def test_is_image_chunk_detection():
    assert _is_image_chunk("![img](https://xxx/1.png)")
    assert not _is_image_chunk("正常文本内容")


def test_kb_hit_verified_entry_checks():
    assert _is_verified_kb_entry(_marked_hit())
    assert not _is_verified_kb_entry(_marked_hit(score=0.3))       # 相似度不足
    assert not _is_verified_kb_entry(_marked_hit(content="无标记内容"))  # 仅0分时由内容判定
    assert not _is_verified_kb_entry(None)


# ---- retrieve_kb：过滤图像块/无标记；SDK异常降级 ----
def test_retrieve_kb_excludes_image_and_unmarked(monkeypatch):
    class FakeChunk:
        def __init__(self, content, score):
            self.content = content
            self.score = score

    class FakeResp:
        def __init__(self, chunks):
            self.chunks = chunks
            self.code = 0

    class FakeClient:
        def __init__(self, config=None):
            pass

        def search(self, query, top_k=3, min_score=0.0):
            return FakeResp([
                FakeChunk("【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6 体育与健康课程核心素养包括运动能力、健康行为和体育品德。", 0.7),
                FakeChunk("![img](https://x/1.png)", 0.9),          # 图像块：跳过
                FakeChunk("无来源标记的标题片段", 0.8),              # 无标记：跳过
            ])

    monkeypatch.setattr(kb_adapter, "Config", lambda: object())
    monkeypatch.setattr(kb_adapter, "KnowledgeClient", FakeClient)
    r = kb_adapter.retrieve_kb(queries=["核心素养"], top_k=5, min_score=0.5)
    assert r["ok"] is True
    hits = r["hits"]["核心素养"]
    assert len(hits) == 1
    assert hits[0].source_file == "Part1A_Core_Health.pdf" and hits[0].page == "6"


def test_retrieve_kb_degrades_on_sdk_error(monkeypatch):
    class BoomClient:
        def __init__(self, config=None):
            raise RuntimeError("sdk down")

    monkeypatch.setattr(kb_adapter, "Config", lambda: object())
    monkeypatch.setattr(kb_adapter, "KnowledgeClient", BoomClient)
    r = kb_adapter.retrieve_kb(queries=["任何问题"])
    assert r["ok"] is False and r["hits"] == {}
    assert r["status"] == "client_error"


# ---- build_draft：人工核验支持当前陈述 → kb_evidence ----
def test_build_draft_adds_kb_evidence_when_verified_hit():
    plan = build_draft(_inp(), kb_evidence=[_marked_hit()])
    kb_evs = [e for e in plan.evidence_log if e.source == EvidenceSource.KB_EVIDENCE]
    assert kb_evs, "可核验命中应新增 kb_evidence 证据"
    assert all(e.citation for e in kb_evs)  # 引用可回溯（文件|页码）
    assert "人工核验A级教学依据" in kb_evs[0].statement


# ---- build_draft：无可核验命中 → 降级 unverified，不虚构 ----
def test_build_draft_degrades_to_unverified_without_kb_evidence():
    plan = build_draft(_inp())  # 默认不传/无命中
    kb_evs = [e for e in plan.evidence_log if e.source == EvidenceSource.KB_EVIDENCE]
    assert kb_evs == []  # 不虚构知识库证据
    unv = [e for e in plan.evidence_log if e.source == EvidenceSource.UNVERIFIED]
    assert unv and all(e.citation is None for e in unv)


def test_build_draft_skips_low_score_or_unmarked(monkeypatch):
    plan = build_draft(_inp(), kb_evidence=[_marked_hit(score=0.3)])
    kb_evs = [e for e in plan.evidence_log if e.source == EvidenceSource.KB_EVIDENCE]
    assert kb_evs == []  # 低相似度不纳入


def test_kb_integration_output_serializable_and_citation():
    plan = build_draft(_inp(), kb_evidence=[_marked_hit()])
    d = json.loads(draft_to_json(plan))
    assert "kb_evidence" in {e["source"] for e in d["evidence_log"]}
    # 教案仍为有效七要素/45分钟
    assert sum(p["minutes"] for p in d["teaching_flow"]["phases"]) == 45

# 第一轮可靠性修复：证据与人工支持关系必须分离。
@pytest.mark.parametrize("body", [
    "", "核心素养内涵", "目录\n核心素养内涵……12\n课程目标……15",
    "课程性质\n课程理念\n课程目标\n核心素养内涵",
    "![任意图片](https://example.invalid/page.png)",
    "<img src='page.png'>",
])
def test_non_body_never_becomes_a_even_with_human_record(body):
    hit = _marked_hit(content="【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6 " + body)
    assert classify_evidence(hit) is EvidenceGrade.C
    plan = build_draft(_inp(), [hit])
    assert not any(e.source is EvidenceSource.KB_EVIDENCE for e in plan.evidence_log)
    assert any(e.source is EvidenceSource.UNVERIFIED for e in plan.evidence_log)


@pytest.mark.parametrize("updates", [
    {"source_file": "other.pdf"}, {"page": "999"},
    {"content": "【原文出处】other.pdf | 原PDF第8页 体育与健康课程核心素养包括运动能力、健康行为和体育品德。"},
    {"content": "【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 【原文出处】other.pdf | 原PDF第8页 体育与健康课程核心素养包括运动能力、健康行为和体育品德。"},
])
def test_inconsistent_or_ambiguous_source_rejected(updates):
    hit = _marked_hit().model_copy(update=updates)
    assert classify_evidence(hit) is EvidenceGrade.C
    assert not _is_verified_kb_entry(hit)


def test_score_and_self_reported_grade_do_not_prove_support():
    hit = _marked_hit(score=1.0).model_copy(update={"human_verification": None})
    assert classify_evidence(hit) is EvidenceGrade.B
    assert not _is_verified_kb_entry(hit)
    # KBHit 忽略不受信任的自报等级，不能用于升级。
    untrusted = KBHit(**{**hit.model_dump(), "grade": "A", "verified": True})
    assert classify_evidence(untrusted) is EvidenceGrade.B


@pytest.mark.parametrize("updates", [
    {"supported_statement": "学生必须达到某个膝关节角度。"},
    {"supports_statement": False}, {"content": "修改后的正文"},
    {"source_file": "other.pdf"}, {"page": "7"},
])
def test_human_review_must_bind_exact_content_source_and_statement(updates):
    hit = _marked_hit()
    review = HumanVerification(**{**hit.human_verification.model_dump(), **updates})
    hit = hit.model_copy(update={"human_verification": review})
    assert classify_evidence(hit) is EvidenceGrade.B
    assert not _is_verified_kb_entry(hit)


def test_a_evidence_supports_only_reviewed_statement():
    hit = _marked_hit()
    assert classify_evidence(hit) is EvidenceGrade.A
    assert classify_evidence(hit, statement="另一教学结论") is EvidenceGrade.B
    plan = build_draft(_inp(), [hit])
    evidence = [e for e in plan.evidence_log if e.source is EvidenceSource.KB_EVIDENCE]
    assert len(evidence) == 1
    assert evidence[0].statement == "【人工核验A级教学依据】" + DEFAULT_STATEMENT


def test_injected_client_does_not_initialize_config_or_need_credentials(monkeypatch):
    from types import SimpleNamespace
    for name in ("COZE_API_TOKEN", "COZE_WORKLOAD_IDENTITY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    def forbidden_config():
        pytest.fail("注入客户端时不得初始化任何 SDK 配置")
    monkeypatch.setattr(kb_adapter, "Config", forbidden_config)
    hit = _marked_hit()
    class Client:
        def search(self, **kwargs):
            return SimpleNamespace(chunks=[SimpleNamespace(
                content=hit.content, score=.9, human_verification=hit.human_verification)])
    result = kb_adapter.retrieve_kb(["核心素养"], client=Client())
    assert result["status"] == "ok"
    candidate = result["hits"]["核心素养"][0]
    assert candidate.human_verification is None  # 远端返回值不能注入人审记录
    assert classify_evidence(candidate) is EvidenceGrade.B


def test_configuration_error_is_distinct_and_sanitized():
    def missing_config():
        raise RuntimeError("sensitive-token-must-not-leak")
    result = kb_adapter.retrieve_kb(config_factory=missing_config)
    assert result["status"] == "configuration_error"
    assert not result["ok"] and result["hits"] == {}
    assert result["errors"] == [{"stage": "configuration", "type": "RuntimeError"}]
    assert "sensitive-token" not in str(result)


def test_search_error_is_distinct_from_empty_result():
    from types import SimpleNamespace
    class Broken:
        def search(self, **kwargs):
            raise RuntimeError("offline")
    class Empty:
        def search(self, **kwargs):
            return SimpleNamespace(chunks=[])
    error = kb_adapter.retrieve_kb(["x"], client=Broken())
    empty = kb_adapter.retrieve_kb(["x"], client=Empty())
    assert error["status"] == "search_error" and not error["ok"]
    assert empty["status"] == "no_evidence" and not empty["ok"]
    assert empty["errors"] == []


def test_factory_injection_avoids_real_sdk():
    from types import SimpleNamespace
    config = object()
    def factory(*, config):
        assert config is sentinel
        return SimpleNamespace(search=lambda **kwargs: SimpleNamespace(chunks=[]))
    sentinel = config
    result = kb_adapter.retrieve_kb(["x"], config_factory=lambda: config, client_factory=factory)
    assert result["status"] == "no_evidence"
