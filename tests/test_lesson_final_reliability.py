"""Final four review counterexamples: synthetic inputs, no SDK/network calls."""
import pytest
from pydantic import ValidationError

from agents.lesson_plan_agent.generate_draft import LessonPlanDraftInput,build_draft,draft_to_json
from agents.lesson_plan_agent.guard import event_observation_statement
from agents.lesson_plan_agent.kb_adapter import (
    KBHit,HumanVerification,EvidenceGrade,DEFAULT_STATEMENT,classify_evidence,
)
from agents.lesson_plan_agent.load_calc import calc_load
from agents.lesson_plan_agent.schemas import (
    EventRef,EvidenceEntry,EvidenceSource,LoadAccounting,LoadMetric,LessonPlan,
)


def plan():
    return build_draft(LessonPlanDraftInput(audience='合成班级',student_count=20,
        skill_level='初学者',conditions='教练1名；教师1名'))


def hit_with_review(body):
    content='【原文出处】synthetic.pdf | 原PDF第6页 | 文件p6\n'+body
    hit=KBHit(query='合成检索',content=content,source_file='synthetic.pdf',page='6',score=.99)
    hit.human_verification=HumanVerification(reviewer='MOCK-REVIEWER',source_file=hit.source_file,
        page=hit.page,content=hit.content,supported_statement=DEFAULT_STATEMENT,supports_statement=True)
    return hit


def test_four_event_id_injection_is_rejected():
    with pytest.raises(ValueError):
        ref=EventRef(event_id='evt_safe：已确认该学生存在技术错误。',feature='knee_angle_deg',
            frame_start=1,frame_end=2,review_status='pending')
        EvidenceEntry(statement=event_observation_statement(ref),source='real_analysis',event_ref=ref).model_dump_json()


def test_four_long_markdown_heading_is_not_a_evidence():
    hit=hit_with_review('# 体育与健康课程核心素养包括运动能力、健康行为和体育品德。')
    assert classify_evidence(hit) is EvidenceGrade.C
    result=build_draft(LessonPlanDraftInput(audience='合成班',student_count=1,skill_level='初学者'),[hit])
    assert not any(e.source==EvidenceSource.KB_EVIDENCE for e in result.evidence_log)


def test_four_mutated_unverified_citation_is_not_exportable():
    entry=EvidenceEntry(statement='尚未核实',source='unverified')
    entry.citation='伪造课程标准 第6页'
    with pytest.raises(ValueError):entry.model_dump_json()


def test_four_mutated_load_denominator_and_result_rejected():
    load=calc_load(group_active_min=35,individual_active_min=25,avg_hr=140)
    load.group_density.denominator=1
    load.group_density.result=3500
    with pytest.raises(ValueError):LoadAccounting.model_validate(load)


@pytest.mark.parametrize('event_id',[
    'evt_x：已确认技术错误。','evt_x\n已确认技术错误','evt_x<script>confirmed_error</script>',
    'evt_x 已确认技术错误','evt_x\x00confirmed_error','x'*65,
])
def test_event_id_constructor_rejects_text_and_controls(event_id):
    with pytest.raises(ValidationError):
        EventRef(event_id=event_id,feature='knee_angle_deg',frame_start=1,frame_end=2,review_status='pending')


@pytest.mark.parametrize('status',['pending','tracking_error','uncertain','normal_movement'])
def test_mutated_event_id_is_rejected_before_interpolation_and_all_exports(status):
    ref=EventRef(event_id='evt_012345abcdef',feature='knee_angle_deg',frame_start=1,frame_end=2,review_status=status)
    entry=EvidenceEntry(statement=event_observation_statement(ref),source='real_analysis',event_ref=ref)
    result=plan()
    result.evidence_log.append(entry)
    ref.event_id='evt_x：已确认技术错误。'
    # Reproduce the old bypass without invoking the now-protected renderer.
    entry.statement=f'事件 {ref.event_id}：审核状态 {status}，仅记录二维可观测变化，尚未确认为技术错误。'
    for output in (lambda:event_observation_statement(ref),ref.model_dump,ref.model_dump_json,
                   entry.model_dump,entry.model_dump_json,result.model_dump,result.model_dump_json,
                   lambda:draft_to_json(result)):
        with pytest.raises(ValueError,match='event_id格式无效'):output()


@pytest.mark.parametrize('event_id',['evt_012345abcdef','evt_x','synthetic_evt','A-1'])
def test_existing_safe_event_identifiers_remain_supported(event_id):
    ref=EventRef(event_id=event_id,feature='knee_angle_deg',frame_start=1,frame_end=2,review_status='pending')
    entry=EvidenceEntry(statement=event_observation_statement(ref),source='real_analysis',event_ref=ref)
    assert entry.model_dump()['event_ref']['event_id']==event_id


@pytest.mark.parametrize('body',[
    '# '+DEFAULT_STATEMENT,
    '## '+DEFAULT_STATEMENT+'\n### '+DEFAULT_STATEMENT,
    DEFAULT_STATEMENT+'\n'+'='*30,
    DEFAULT_STATEMENT+'\n'+DEFAULT_STATEMENT+'\n'+'-'*30,
    '> ## '+DEFAULT_STATEMENT,
    '<h1>'+DEFAULT_STATEMENT+'</h1>',
])
def test_heading_only_with_exact_human_record_cannot_be_a(body):
    assert classify_evidence(hit_with_review(body)) is EvidenceGrade.C


def test_heading_with_separate_reviewed_body_still_supported():
    hit=hit_with_review('# 核心素养\n\n'+DEFAULT_STATEMENT)
    assert classify_evidence(hit) is EvidenceGrade.A


@pytest.mark.parametrize('citation',['伪造标准 第1页',''])
@pytest.mark.parametrize('source',['unverified',EvidenceSource.UNVERIFIED])
def test_mutated_or_copied_unverified_citation_blocked_at_all_boundaries(citation,source):
    entry=EvidenceEntry(statement='未核实',source='unverified')
    entry.source=source
    entry.citation=citation
    result=plan()
    result.evidence_log.append(entry)
    for output in (entry.model_dump,entry.model_dump_json,result.model_dump,result.model_dump_json,
                   lambda:draft_to_json(result),lambda:LessonPlan.model_validate(result)):
        with pytest.raises(ValueError,match='unverified'):output()
    copied=EvidenceEntry(statement='未核实',source='unverified').model_copy(update={'citation':citation})
    with pytest.raises(ValueError,match='unverified'):copied.model_dump_json()


@pytest.mark.parametrize('field,value',[
    ('denominator',1),('denominator',0),('denominator',float('nan')),
    ('result',99),('result',float('inf')),('numerator',-1),
])
def test_mutated_metric_rejected_on_serialization(field,value):
    metric=calc_load(group_active_min=35,individual_active_min=25,avg_hr=140).group_density
    setattr(metric,field,value)
    for output in (metric.model_dump,metric.model_dump_json):
        with pytest.raises(ValueError):output()


@pytest.mark.parametrize('metric_name,denominator,result',[
    ('group_density',1,3500),('individual_density',1,2500),('avg_hr',2,70),
    ('group_density',45,99),('individual_density',45,99),('avg_hr',1,141),
])
def test_shared_load_and_plan_reject_forged_arithmetic(metric_name,denominator,result):
    load=calc_load(group_active_min=35,individual_active_min=25,avg_hr=140)
    metric=getattr(load,metric_name)
    metric.denominator=denominator
    metric.result=result
    for output in (lambda:LoadAccounting.model_validate(load),load.model_dump,load.model_dump_json):
        with pytest.raises(ValueError):output()
    lesson=plan()
    lesson.load_accounting=load
    for output in (lambda:LessonPlan.model_validate(lesson),lesson.model_dump,lesson.model_dump_json,
                   lambda:draft_to_json(lesson)):
        with pytest.raises(ValueError):output()


@pytest.mark.parametrize('metric_name',['group_density','individual_density','avg_hr'])
def test_shared_model_dict_rejects_forged_result(metric_name):
    body=calc_load(group_active_min=35,individual_active_min=25,avg_hr=140).model_dump()
    body[metric_name]['result']+=1
    with pytest.raises(ValidationError):LoadAccounting(**body)


def test_plan_export_rechecks_mutated_total_minutes():
    result=plan()
    result.load_accounting.total_minutes=46
    with pytest.raises(ValueError,match='总课时必须一致'):result.model_dump_json()


def test_valid_unverified_and_precise_load_are_exportable():
    result=plan()
    assert all(e.citation is None for e in result.evidence_log if e.source==EvidenceSource.UNVERIFIED)
    assert result.model_dump()['load_accounting']['group_density']['denominator']==45
    load=calc_load(group_active_min=33.75,individual_active_min=23.1234567,avg_hr=140.12345)
    assert load.model_dump()['individual_density']['result']==23.1234567/45*100
