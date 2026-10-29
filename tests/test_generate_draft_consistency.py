"""教案生成 Agent —— 任务1.1 跨字段一致性与课堂可执行性校验 回归测试。

覆盖五项修复：
1. 师资数量与输入一致（不自行增设人员）。
2. 能力层级(3级)与轮换组(4组)的对应关系明确。
3. 密度数值标记为"设计目标，尚未由课堂安排验证"（不声称必然达标）。
4. 删除不适用于所有情形的绝对化安全处置表述，技术要领待专项教练确认。
5. 教学评价为可观察的分层过程性目标，不虚构官方合格线。
"""
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents.lesson_plan_agent.generate_draft import (  # noqa: E402
    LessonPlanDraftInput,
    _build_staffing,
    _parse_staffing,
    build_draft,
    draft_to_json,
)


def _inp(**kw):
    base = dict(audience="小学三年级", student_count=20, skill_level="初学者",
                theme="冰上双足滑行与身体姿态控制",
                conditions="室内冰场，每人一副冰鞋，教练1名，教师1名",
                total_minutes=45, group_active_min=36.0, individual_active_min=25.0, avg_hr=135.0)
    base.update(kw)
    return LessonPlanDraftInput(**base)


# ---- 1. 师资一致性 ----
def test_staffing_matches_input_does_not_inflate():
    plan = build_draft(_inp())
    staffing = plan.safety_precautions.staffing
    assert "教练1名" in staffing and "教师1名" in staffing
    assert "教练2" not in staffing  # 输入为教练1名，不得自行增至教练2


def test_staffing_parse_partial_input():
    # 仅教练人数明确：不得虚构教师人数（首段只有"教练2名"）
    st = _build_staffing("室内冰场；教练2人")
    assert st.split("；")[0] == "教练2名"
    assert _parse_staffing("室内冰场；教练2人")["教师"] is None


def test_staffing_parse_missing():
    st = _build_staffing("室内冰场；冰鞋若干")
    p = _parse_staffing("室内冰场；冰鞋若干")
    assert p["教练"] is None and p["教师"] is None
    assert "不自行增设人员" in st


# ---- 2. 分组一致性 ----
def test_tier_and_rotation_mapping_explicit():
    plan = build_draft(_inp())
    tiered = plan.learner_analysis.tiered_plan
    grouping = plan.venue_equipment.grouping
    assert "3 个能力层级" in tiered
    assert "2 组" in grouping
    assert plan.venue_equipment.proposed_group_sizes == [10, 10]
    assert "不固定绑定轮换组" in tiered
    assert "待确认" in grouping
    assert "不表示各组可同时上冰" in grouping


# ---- 3. 密度证据不足 ----
def test_density_marked_design_target_not_verified():
    plan = build_draft(_inp())
    note = plan.load_accounting.note
    assert "预计值" in note
    assert "设计目标" in note
    assert "尚未由课堂环节安排实测验证" in note
    assert "不得声称必然达标" in note
    # 仍保留确定性公式与数值
    assert plan.load_accounting.group_density.result == pytest.approx(80.0)


# ---- 4. 安全措辞 ----
def test_no_universal_absolute_treatment_wording():
    plan = build_draft(_inp())
    emg = plan.safety_precautions.emergency_flow
    main_tip = next(p.safety_tip for p in plan.teaching_flow.phases
                    if p.phase.value == "main")
    # 不再出现针对所有情形的绝对化处置
    assert "摔倒后原地待援；出现不适立即示意，由教师按应急预案处置并送返休息区" not in emg
    assert "禁止并行抢道与嬉闹；摔倒后原地待援" not in main_tip
    # 技术要领待专项教练确认
    assert "待专项教练确认" in plan.safety_precautions.medical_note
    assert "待专项教练确认" in main_tip


# ---- 5. 教学评价 ----
def test_evaluation_is_observable_tiered_and_not_official_line():
    plan = build_draft(_inp())
    ev = next(p.evaluation for p in plan.teaching_flow.phases if p.phase.value == "main")
    assert "层级①" in ev and "层级②" in ev and "层级③" in ev  # 可观察分层描述
    assert "实际教学人员拟定的过程性观察目标" in ev
    assert "非官方技术合格线" in ev


def test_consistency_output_serializable():
    plan = build_draft(_inp())
    import json
    d = json.loads(draft_to_json(plan))
    assert d["safety_precautions"]["staffing"]
    assert "设计目标" in d["load_accounting"]["note"]