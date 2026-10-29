"""教案生成 Agent —— 任务1 教案草稿生成器 单元测试。

覆盖：七要素齐全、三段式 45 分钟强校验、负荷/密度可复核、错误输入被拒绝、
课标未核实标记（不虚构引用）、未审核事件保护、花滑技术建议"待教练确认"、
输出可序列化 JSON。
"""
import json
import os
import sys

import pytest
from pydantic import ValidationError

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents.lesson_plan_agent.generate_draft import (  # noqa: E402
    LessonPlanDraftInput,
    build_draft,
    draft_to_json,
)
from agents.lesson_plan_agent.guard import validate_event_claims  # noqa: E402
from agents.lesson_plan_agent.schemas import (  # noqa: E402
    EvidenceSource,
    ReviewStatus,
    TeachingPhase,
)


def _inp(**kw):
    base = dict(audience="小学三年级", student_count=30, skill_level="初学者",
                theme="冰上双足滑行与身体姿态控制", conditions="标准冰场1片；教练2人",
                total_minutes=45, group_active_min=36.0, individual_active_min=25.0, avg_hr=145.0)
    base.update(kw)
    return LessonPlanDraftInput(**base)


def test_build_plan_seven_elements_present():
    plan = build_draft(_inp())
    # 七要素逐个存在且非空
    assert plan.guiding_ideology.content
    assert plan.teaching_material_analysis.technical_composition
    assert plan.learner_analysis.student_profile
    assert plan.venue_equipment.zones
    assert plan.safety_precautions.emergency_flow
    assert plan.teaching_flow.phases
    assert plan.load_accounting.group_density.result
    assert plan.review_status == ReviewStatus.DRAFT


def test_teaching_flow_total_and_ranges():
    plan = build_draft(_inp())
    total = sum(p.minutes for p in plan.teaching_flow.phases)
    assert total == 45
    by = {p.phase: p.minutes for p in plan.teaching_flow.phases}
    assert by[TeachingPhase.PREP] == 9           # 8-10
    assert by[TeachingPhase.MAIN] == 29          # 28-30
    assert by[TeachingPhase.CLOSING] == 7        # 5-7


def test_phase_detail_fields_nonempty():
    plan = build_draft(_inp())
    fields = ("teacher_activity", "student_activity", "organization", "safety_tip", "evaluation")
    for p in plan.teaching_flow.phases:
        for f in fields:
            assert getattr(p, f).strip(), f"阶段 {p.phase.value} 缺少 {f}"


def test_load_calculation_verifiable():
    plan = build_draft(_inp())
    g = plan.load_accounting.group_density
    i = plan.load_accounting.individual_density
    hr = plan.load_accounting.avg_hr
    # 公式含分子/分母；结果为 活动时间/45
    assert g.formula and g.numerator == pytest.approx(36.0) and g.denominator == 45.0
    assert g.result == pytest.approx(80.0)      # 36/45
    assert i.result == pytest.approx(25 / 45 * 100, rel=1e-2)
    assert hr.result == pytest.approx(145.0)
    assert "预计值" in plan.load_accounting.note  # 无实测一律预计


def test_error_input_rejected():
    with pytest.raises(ValidationError):
        _inp(student_count=0)
    with pytest.raises(ValidationError):
        _inp(audience="")
    with pytest.raises(Exception):
        _inp(total_minutes=50)           # 非45分钟
    with pytest.raises(Exception):
        _inp(group_active_min=60)        # 超过总课时
    with pytest.raises(Exception):
        _inp(individual_active_min=-1)


def test_kb_not_connected_is_unverified_no_fabricated_citation():
    plan = build_draft(_inp())
    unv = [e for e in plan.evidence_log if e.source == EvidenceSource.UNVERIFIED]
    assert unv, "应存在知识库未核实来源标记"
    for e in unv:
        assert e.citation is None, "未核实时不得虚构出处"
        assert "知识库未核实" in e.statement


def test_no_event_described_as_confirmed_error():
    plan = build_draft(_inp())
    v = validate_event_claims(plan.evidence_log)
    assert v == []  # 无任何"未审核事件写成已确认"违规
    bad_prefixes = ("已确认", "确诊", "确定是错误", "认定为技术错误")
    for e in plan.evidence_log:
        if e.source in (EvidenceSource.REAL_ANALYSIS,):
            assert not e.statement.lstrip().startswith(bad_prefixes)


def test_tech_suggestions_pend_coach_no_threshold():
    plan = build_draft(_inp())
    text = (plan.teaching_material_analysis.note_2d_limitation
            + plan.teaching_material_analysis.difficulties)
    assert "待专业教练确认" in plan.teaching_material_analysis.note_2d_limitation
    assert "不设" in plan.teaching_material_analysis.note_2d_limitation  # 不虚构合格阈值


def test_output_is_serializable_json():
    plan = build_draft(_inp())
    s = draft_to_json(plan)
    d = json.loads(s)
    for k in ("title", "teacher_input", "guiding_ideology", "teaching_material_analysis",
              "learner_analysis", "venue_equipment", "safety_precautions",
              "teaching_flow", "load_accounting", "evidence_log"):
        assert k in d
    assert d["teaching_flow"]["phases"]  # 三段式在 JSON 中
    assert d["review_status"] == "draft"