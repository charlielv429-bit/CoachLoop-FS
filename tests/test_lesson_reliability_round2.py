"""第二轮五类漏洞的最小反例与输出边界回归；仅使用合成输入。"""
import json
import pytest
from pydantic import ValidationError
from agents.lesson_plan_agent.generate_draft import (
    LessonPlanDraftInput, build_draft, draft_to_json,
)
from agents.lesson_plan_agent.guard import event_observation_statement, validate_event_claims
from agents.lesson_plan_agent.load_calc import calc_load, min_activity_for_targets
from agents.lesson_plan_agent.schemas import (
    EvidenceEntry, EventRef, EventClaim, LessonPlan, MeasurementKind,
)


def draft_input(**overrides):
    data = dict(audience="合成测试班", student_count=20, skill_level="初学者",
                conditions="教练1名；教师1名")
    return LessonPlanDraftInput(**{**data, **overrides})


@pytest.mark.parametrize("count,conditions,sizes", [
    (1, "教练1名；教师0名", [1]),
    (20, "教练1名；教师1名", [10, 10]),
    (20, "教练2名；教师1名", [7, 7, 6]),
    (1, "教练3名；教师3名", [1]),
    (20, "教练0名；教师2名", []),
    (20, "教练1名", []),
    (20, "冰场一片", []),
])
def test_grouping_is_bounded_by_explicit_people_and_pending(count, conditions, sizes):
    plan = build_draft(draft_input(student_count=count, conditions=conditions))
    venue = plan.venue_equipment
    assert venue.proposed_group_sizes == sizes
    assert venue.organization_status == "pending_confirmation"
    if sizes:
        assert sum(sizes) == count and all(n > 0 for n in sizes)
    else:
        assert "暂不制定可执行分组" in venue.grouping
    for phase in plan.teaching_flow.phases:
        assert venue.grouping in phase.organization
    assert "教师位于" not in draft_to_json(plan)
    if count == 1:
        assert "两人一组" not in draft_to_json(plan)


def test_missing_staff_does_not_invent_defaults():
    inp = LessonPlanDraftInput(audience="合成班级", student_count=20, skill_level="初学者")
    assert inp.conditions == ""
    plan = build_draft(inp)
    assert plan.venue_equipment.proposed_group_sizes == []
    assert "教练2" not in draft_to_json(plan)
    assert "不自行增设人员" in plan.safety_precautions.staffing


def test_conflicting_staff_counts_are_rejected():
    with pytest.raises(ValidationError, match="人数存在冲突"):
        draft_input(conditions="教练1名；教练2名；教师1名")


def test_fall_policy_is_consistent_and_unreviewed_everywhere():
    plan = build_draft(draft_input())
    common = "摔倒、起身与制动的具体处置方式待专项教练确认，按现场风险和学校应急预案执行；本稿不提供统一处置指令。"
    texts = [plan.guiding_ideology.healthy_behavior,
             plan.safety_precautions.emergency_flow,
             plan.safety_precautions.medical_note,
             *(p.safety_tip for p in plan.teaching_flow.phases)]
    assert all(common in t for t in texts)
    assert plan.safety_precautions.safety_review_status == "unreviewed"
    assert "普通教学提示（未经专项安全审核）" in plan.safety_precautions.emergency_flow
    serialized = draft_to_json(plan)
    for forbidden in ("原地待援", "扶栏等待", "立即", "全程", "禁止奔跑"):
        assert forbidden not in serialized


def event_entry(status="pending", statement=None, claim=EventClaim.OBSERVATION):
    ref = EventRef(event_id="synthetic_evt", feature="knee_angle_deg", frame_start=1,
                   frame_end=2, review_status=status)
    return EvidenceEntry(statement=statement or event_observation_statement(ref),
                         source="real_analysis", event_ref=ref, event_claim=claim)


@pytest.mark.parametrize("status", ["pending", "tracking_error", "uncertain", "normal_movement"])
@pytest.mark.parametrize("statement", [
    "视频表明：已确认该学生存在技术错误", "分析结论：这个动作肯定有错", "技术错误已经确认",
])
def test_unconfirmed_free_text_cannot_bypass_structured_guard(status, statement):
    entry = event_entry(status, statement)
    assert validate_event_claims([entry])
    with pytest.raises(ValueError, match="尚未经教练确认"):
        entry.model_dump_json()


@pytest.mark.parametrize("status", ["pending", "tracking_error", "uncertain", "normal_movement"])
def test_error_claim_rejected_even_with_neutral_text(status):
    entry = event_entry(status, claim=EventClaim.CONFIRMED_ERROR)
    assert validate_event_claims([entry])


@pytest.mark.parametrize("status", ["pending", "tracking_error", "uncertain", "normal_movement"])
def test_structured_observations_can_be_exported(status):
    entry = event_entry(status)
    assert validate_event_claims([entry]) == []
    assert json.loads(entry.model_dump_json())["event_claim"] == "observation"


def test_confirmed_error_requires_confirmed_status():
    entry = event_entry("confirmed", "经教练确认的技术错误", EventClaim.CONFIRMED_ERROR)
    assert validate_event_claims([entry]) == []
    assert json.loads(entry.model_dump_json())["event_claim"] == "confirmed_error"
    with pytest.raises(ValidationError):
        event_entry("unrecognized")


def test_event_guard_runs_on_plan_construction_and_all_output_paths():
    plan = build_draft(draft_input())
    # 不调用违规条目的 serializer，直接构造模型输入，验证构造边界。
    invalid_data = dict(statement="视频表明：已确认技术错误", source="real_analysis",
                        event_ref=dict(event_id="synthetic_evt", feature="knee_angle_deg",
                                       frame_start=1, frame_end=2, review_status="pending"))
    body = plan.model_dump()
    body["evidence_log"].append(invalid_data)
    with pytest.raises(ValidationError, match="尚未经教练确认"):
        LessonPlan(**body)
    # 构造后修改也不能绕过对外输出检查。
    plan.evidence_log.append(event_entry(statement=invalid_data["statement"]))
    for output in (lambda: draft_to_json(plan), plan.model_dump, plan.model_dump_json):
        with pytest.raises(ValueError, match="尚未经教练确认"):
            output()


def test_real_analysis_without_review_reference_is_not_exportable():
    entry = EvidenceEntry(statement="已确认技术错误", source="real_analysis")
    assert validate_event_claims([entry])
    with pytest.raises(ValueError, match="必须提供 event_ref"):
        entry.model_dump_json()


@pytest.mark.parametrize("field", ["total_minutes", "group_active_min", "individual_active_min", "avg_hr"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1])
def test_invalid_load_values_rejected_by_function_and_draft(field, value):
    values = dict(total_minutes=45, group_active_min=33.75, individual_active_min=22.5, avg_hr=140)
    values[field] = value
    with pytest.raises(ValueError):
        calc_load(**values)
    with pytest.raises(ValidationError):
        draft_input(**{field: value})


@pytest.mark.parametrize("heart_rate", [0, 1, 19.9, 250.1, 999])
def test_obviously_invalid_heart_rates_rejected(heart_rate):
    with pytest.raises(ValueError, match="数据有效域"):
        calc_load(avg_hr=heart_rate)
    with pytest.raises(ValidationError):
        draft_input(avg_hr=heart_rate)


def test_raw_precision_is_retained_and_only_display_is_rounded():
    load = calc_load(group_active_min=33.75, individual_active_min=23.1234567, avg_hr=140.12345)
    metric = load.individual_density
    assert load.group_density.numerator == 33.75
    assert load.group_density.result == 75.0
    assert metric.numerator == 23.1234567
    assert metric.result == metric.numerator / metric.denominator * 100
    assert metric.display_result == round(metric.result, 2)
    assert metric.result != metric.display_result
    assert load.avg_hr.result == 140.12345
    assert "33.75 / 45 * 100" in load.group_density.formula
    assert min_activity_for_targets()["min_group_active_min"] == 33.75


@pytest.mark.parametrize("kind", [MeasurementKind.ESTIMATED, MeasurementKind.MEASURED, "estimated", "measured"])
def test_measurement_labels_formulas_and_data_agree(kind):
    load = calc_load(avg_hr=140.12345, kind=kind)
    label = "实测" if kind == "measured" else "预计"
    assert load.avg_hr.name == label + "平均心率"
    assert label + "输入值" in load.avg_hr.formula
    assert load.avg_hr.numerator == load.avg_hr.result == 140.12345
    assert all(m.kind == kind for m in (load.avg_hr, load.group_density, load.individual_density))
    if label == "实测":
        assert "非实测" not in load.avg_hr.formula
        assert "预计" not in load.note


@pytest.mark.parametrize("field,value", [
    ("theme", "单足旋转"), ("theme", "基础滑行"),
    ("skill_level", "中级"), ("skill_level", "高级"),
])
def test_unsupported_template_rejected_at_input_and_generation(field, value):
    with pytest.raises(ValidationError, match="未支持"):
        draft_input(**{field: value})
    # model_copy 不验证更新；生成边界必须再验证，不能只替换标题。
    forged = draft_input().model_copy(update={field: value})
    with pytest.raises(ValidationError, match="未支持"):
        build_draft(forged)


def test_mutated_review_status_and_source_cannot_bypass_output_guard():
    entry = event_entry()
    entry.event_ref.review_status = "invented_status"
    entry.statement = event_observation_statement(entry.event_ref)
    with pytest.raises(ValueError, match="审核状态无效"):
        entry.model_dump_json()
    entry = EvidenceEntry(statement="已确认技术错误", source="teacher_input")
    entry.source = "real_analysis"
    with pytest.raises(ValueError, match="必须提供 event_ref"):
        entry.model_dump_json()


def test_invalid_heart_rate_cannot_enter_plan_through_shared_model():
    plan = build_draft(draft_input())
    body = plan.model_dump()
    body["load_accounting"]["avg_hr"]["result"] = 999
    with pytest.raises(ValidationError, match="数据有效域"):
        LessonPlan(**body)
