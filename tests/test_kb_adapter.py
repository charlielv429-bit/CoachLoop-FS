"""教案生成 Agent —— 任务2A 最小知识库接入 回归测试。

覆盖：
- 适配器仅把带【原文出处】来源标记、非图像块、达标(=score≥阈值)的命中视为可核验；
- 图像块/无来源标记/SDK异常一律返回空（不虚构引用）；
- build_draft 在提供可核验命中时新增 kb_evidence，且引用可回溯；
- 知识库不可用/无可核验命中时，教案仍可降级生成，维持 unverified。
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
from agents.lesson_plan_agent.kb_adapter import KBHit, _parse_citation, _is_image_chunk  # noqa: E402
from agents.lesson_plan_agent.schemas import EvidenceSource  # noqa: E402


def _inp(**kw):
    base = dict(audience="小学三年级", student_count=20, skill_level="初学者",
                theme="冰上双足滑行与身体姿态控制",
                conditions="室内冰场，每人一副冰鞋，教练1名，教师1名",
                total_minutes=45, group_active_min=36.0, individual_active_min=25.0, avg_hr=135.0)
    base.update(kw)
    return LessonPlanDraftInput(**base)


def _marked_hit(query="体育与健康学科核心素养包括什么？", content=None, score=0.62):
    return KBHit(
        query=query,
        content=content or "【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6  课程性质  课程理念  课程目标  核心素养内涵",
        source_file="Part1A_Core_Health.pdf",
        page="6",
        score=score,
    )


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
                FakeChunk("【原文出处】Part1A_Core_Health.pdf | 原PDF第6页 | 文件p6 核心素养内涵", 0.7),
                FakeChunk("![img](https://x/1.png)", 0.9),          # 图像块：跳过
                FakeChunk("无来源标记的标题片段", 0.8),              # 无标记：跳过
            ])

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

    monkeypatch.setattr(kb_adapter, "KnowledgeClient", BoomClient)
    r = kb_adapter.retrieve_kb(queries=["任何问题"])
    assert r["ok"] is False and r["hits"] == {}


# ---- build_draft：真实可核验命中 → kb_evidence ----
def test_build_draft_adds_kb_evidence_when_verified_hit():
    plan = build_draft(_inp(), kb_evidence=[_marked_hit()])
    kb_evs = [e for e in plan.evidence_log if e.source == EvidenceSource.KB_EVIDENCE]
    assert kb_evs, "可核验命中应新增 kb_evidence 证据"
    assert all(e.citation for e in kb_evs)  # 引用可回溯（文件|页码）
    assert "已核实" in kb_evs[0].statement


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