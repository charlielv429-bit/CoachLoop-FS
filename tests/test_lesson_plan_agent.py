"""CoachLoop-FS 教案生成 Agent（阶段 A）单元测试。

覆盖：七要素缺项校验、三段式 45 分钟强校验、负荷/密度确定性核算、来源与
"未核实"标记、未审核事件不得描述为已确认技术错误。全为纯逻辑，无外部依赖。
"""
import json
import os
import sys

import pytest
from pydantic import ValidationError

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents.lesson_plan_agent.guard import (  # noqa: E402
    can_describe_as_confirmed,
    unverified_kb,
    validate_event_claims,
)
from agents.lesson_plan_agent.load_calc import (  # noqa: E402
    calc_load,
    min_activity_for_targets,
)
from agents.lesson_plan_agent.schemas import (  # noqa: E402
    EvidenceEntry,
    EventRef,
    EvidenceSource,
    LessonPlan,
    MeasurementKind,
    Phase,
    TeachingFlow,
    GeneralTeachingFlow,
    TeachingPhase,
)


def _phases(prep=9, main=29, closing=7):
    return [
        Phase(phase=TeachingPhase.PREP, minutes=prep, content="课堂常规、关节激活、冰上适应热身"),
        Phase(phase=TeachingPhase.MAIN, minutes=main, content="示范讲解、分组练习、巩固练习"),
        Phase(phase=TeachingPhase.CLOSING, minutes=closing, content="整理活动、总结、器材回收"),
    ]


def _base_body():
    return {
        "title": "花样滑冰·基础滑行与安全启蒙",
        "teacher_input": {"audience": "小学三年级，30人", "theme": "基础滑行",
                          "conditions": "标准冰场1片，教练2人", "class_data_available": False},
        "guiding_ideology": {"content": "围绕健康第一理念",
                             "motor_competence": "掌握安全站立与直线滑行",
                             "healthy_behavior": "养成热身与装备检查习惯",
                             "sports_ethics": "遵守冰场礼仪与规则"},
        "teaching_material_analysis": {"technical_composition": "站立-滑行-制动",
                                       "key_points": "重心平稳",
                                       "difficulties": "保持平衡",
                                       "progression": "承接上一课站立，为下一课转弯铺垫"},
        "learner_analysis": {"student_profile": "零基础",
                             "common_difficulties": "重心后坐",
                             "tiered_plan": "按站立稳定性分组"},
        "venue_equipment": {"zones": "练习区/缓冲区",
                            "camera_position": "教师对角机位"},
        "safety_precautions": {"risk_screening": "课前健康问询",
                               "ice_check": "冰面平整检查",
                               "equipment_check": "冰鞋/护具检查",
                               "emergency_flow": "摔倒后原地等待教师处置"},
        "teaching_flow": {"total_minutes": 45, "phases": _phases()},
        "load_accounting": {
            "avg_hr": {"name": "预计平均心率", "kind": "estimated", "formula": "x", "numerator": 135,
                       "denominator": 1, "unit": "次/分", "result": 135.0, "target": "预计值"},
            "group_density": {"name": "群体运动密度", "kind": "estimated", "formula": "f", "numerator": 36,
                              "denominator": 45, "unit": "%", "result": 80.0},
            "individual_density": {"name": "个体练习密度", "kind": "estimated", "formula": "g", "numerator": 24,
                                   "denominator": 45, "unit": "%", "result": 53.33},
            "total_minutes": 45,
        },
    }


def _build(**overrides):
    body = {**_base_body(), **overrides}
    return LessonPlan(**body)


# ---------------- 七要素缺项校验 ----------------
class TestSevenElements:
    def test_valid_plan_passes(self):
        plan = _build()
        assert plan.review_status.value == "draft"
        assert plan.load_accounting.total_minutes == 45

    def test_missing_element_fails(self):
        body = _base_body()
        del body["safety_precautions"]  # 缺第 5 要素
        with pytest.raises(ValidationError):
            LessonPlan(**body)

    def test_missing_subfield_fails(self):
        body = _base_body()
        del body["guiding_ideology"]["sports_ethics"]  # 缺"体育品德"
        with pytest.raises(ValidationError):
            LessonPlan(**body)

    def test_empty_required_field_fails(self):
        body = _base_body()
        body["title"] = ""
        with pytest.raises(ValidationError):
            LessonPlan(**body)


# ---------------- 三段式 45 分钟强校验 ----------------
class TestTeachingFlowTime:
    def test_total_must_equal_45(self):
        with pytest.raises(ValidationError, match="合计须严格等于 45"):
            TeachingFlow(total_minutes=45, phases=_phases(prep=10, main=30, closing=8))  # 10+30+8=48

    def test_missing_phase_rejected(self):
        with pytest.raises(ValidationError, match="缺少教学阶段"):
            TeachingFlow(total_minutes=45, phases=_phases()[:2])

    def test_duplicate_phase_rejected(self):
        with pytest.raises(ValidationError, match="阶段重复"):
            TeachingFlow(total_minutes=45, phases=_phases() + [Phase(phase=TeachingPhase.PREP, minutes=9, content="x")])

    def test_phase_range_rejected(self):
        # 准备 5 分钟超出 [8,10]
        with pytest.raises(ValidationError, match="分钟数须在"):
            TeachingFlow(total_minutes=45, phases=_phases(prep=5, main=30, closing=10))  # 5+30+10=45

    def test_different_total_requires_explicit_general_model(self):
        # 标准模型拒绝非45分钟，通用模型保留扩展能力
        with pytest.raises(ValidationError, match="45分钟标准"):
            TeachingFlow(total_minutes=46, phases=_phases(prep=9, main=30, closing=7))
        # 通用模型允许扩展；当前 LessonPlan 不接受它代替标准模式。
        tf = GeneralTeachingFlow(total_minutes=46, phases=_phases(prep=9, main=30, closing=7))
        assert tf.total_minutes == 46


# ---------------- 负荷与密度确定性核算 ----------------
class TestLoadCalc:
    def test_density_formulas_and_units(self):
        acc = calc_load(total_minutes=45, group_active_min=36, individual_active_min=24, avg_hr=135, kind=MeasurementKind.ESTIMATED)
        assert acc.group_density.unit == "%" and acc.group_density.result == 80.0
        assert acc.individual_density.result == pytest.approx(53.33, abs=0.01)
        assert acc.group_density.formula == "group = group_active_min / total_minutes = 36.0 / 45"
        assert acc.group_density.numerator == 36.0 and acc.group_density.denominator == 45.0
        assert acc.avg_hr.kind == MeasurementKind.ESTIMATED
        assert "待课堂实测验证" in acc.note

    def test_measured_kind(self):
        acc = calc_load(total_minutes=45, group_active_min=33.75, individual_active_min=22.5, avg_hr=140, kind=MeasurementKind.MEASURED)
        assert acc.group_density.kind == MeasurementKind.MEASURED
        assert acc.avg_hr.result == 140.0

    def test_min_activity_for_targets(self):
        r = min_activity_for_targets(45)
        assert r["min_group_active_min"] == 33.8  # 45*0.75 round1
        assert r["min_individual_active_min"] == 22.5  # 45*0.5
        assert r["group_target"] == 0.75 and r["individual_target"] == 0.5

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            calc_load(total_minutes=0)
        with pytest.raises(ValueError):
            calc_load(total_minutes=45, group_active_min=50)  # 超过总课时


# ---------------- 来源/数据状态标记 ----------------
class TestSourceMarking:
    def test_unverified_kb_no_fabrication(self):
        note = unverified_kb()
        assert "未核实" in note
        # 知识库未接入时不会携带虚构的引用（无 file/page）
        assert "第" not in note or "章节" not in note  # 提示中不含具体出处

    def test_evidence_source_preserved(self):
        ev = EvidenceEntry(statement="学生为全滑行零基础", source=EvidenceSource.TEACHER_INPUT)
        assert ev.source.value == "teacher_input"
        assert ev.citation is None


# ---------------- 未审核事件不得命名为已确认技术错误 ----------------
class TestEventGuard:
    def _ev(self, status, statement):
        return EvidenceEntry(
            statement=statement,
            source=EvidenceSource.REAL_ANALYSIS,
            event_ref=EventRef(event_id="evt_x", feature="knee_angle_deg",
                                frame_start=41, frame_end=70, review_status=status),
        )

    def test_pending_event_cannot_be_confirmed(self):
        violations = validate_event_claims([self._ev("pending", "已确认该学生屈膝角度异常")])
        assert len(violations) == 1 and "不得描述为已确认技术错误" in violations[0]

    def test_confirmed_event_allowed(self):
        assert can_describe_as_confirmed(self._ev("confirmed", "x").event_ref) is True
        assert validate_event_claims([self._ev("confirmed", "已确认该动作阶段变化明显")]) == []

    def test_uncertain_and_tracking_error_also_blocked(self):
        for st in ("uncertain", "normal_movement", "tracking_error"):
            assert can_describe_as_confirmed(self._ev(st, "x").event_ref) is False

    def test_mild_wording_allowed_for_pending(self):
        # 用"待审核"表述，不触发保护
        assert validate_event_claims([self._ev("pending", "该事件有待审核，尚未确认为错误")]) == []


class TestPlanWithEvidence:
    def test_plan_traces_source(self, tmp_path):
        plan = _build(
            evidence_log=[
                EvidenceEntry(statement="学生为全滑行零基础", source=EvidenceSource.TEACHER_INPUT),
                EvidenceEntry(statement="知识库未核实（未接入课程规范）", source=EvidenceSource.UNVERIFIED, citation=None),
            ]
        )
        payload = plan.model_dump_json(indent=2, ensure_ascii=False)
        parsed = json.loads(payload)
        assert parsed["evidence_log"][1]["source"] == "unverified"
        assert parsed["evidence_log"][1]["citation"] is None
        out_path = tmp_path / "plan.json"
        out_path.write_text(payload, encoding="utf-8")
        assert out_path.exists()

@pytest.mark.parametrize("total, phases", [
    (41, _phases(8, 28, 5)), (46, _phases(9, 30, 7)),
])
def test_non45_cannot_bypass_standard_mode(total, phases):
    with pytest.raises(ValidationError, match="45分钟标准"):
        TeachingFlow(total_minutes=total, phases=phases)
    body = _base_body()
    body["teaching_flow"] = {"total_minutes": total, "phases": phases}
    body["load_accounting"]["total_minutes"] = total
    with pytest.raises(ValidationError, match="45分钟标准"):
        LessonPlan(**body)


@pytest.mark.parametrize("citation", ["虚构文献 第1页", "", "真实文献 第1页"])
def test_unverified_cannot_have_any_citation(citation):
    with pytest.raises(ValidationError, match="unverified"):
        EvidenceEntry(statement="尚未核实", source=EvidenceSource.UNVERIFIED, citation=citation)


def test_load_and_flow_time_must_match():
    body = _base_body()
    body["load_accounting"]["total_minutes"] = 46
    with pytest.raises(ValidationError, match="总课时必须一致"):
        LessonPlan(**body)


def test_standard_plan_rechecks_unvalidated_nested_flow():
    body = _base_body()
    flow = TeachingFlow(phases=_phases())
    body["teaching_flow"] = flow.model_copy(update={"total_minutes": 46})
    with pytest.raises(ValidationError, match="时间合计"):
        LessonPlan(**body)


def test_general_flow_cannot_be_used_as_standard_plan():
    body = _base_body()
    flow = GeneralTeachingFlow(total_minutes=46, phases=_phases(9, 30, 7))
    body["teaching_flow"] = flow.model_dump()
    with pytest.raises(ValidationError, match="45分钟标准"):
        LessonPlan(**body)


def test_general_flow_does_not_inherit_standard_phase_ranges():
    flow = GeneralTeachingFlow(total_minutes=60, phases=_phases(12, 40, 8))
    assert flow.total_minutes == 60
    assert sum(p.minutes for p in flow.phases) == 60
    with pytest.raises(ValidationError):
        TeachingFlow(**flow.model_dump())
