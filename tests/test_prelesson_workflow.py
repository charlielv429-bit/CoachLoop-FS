"""INTEGRATION-02: anonymous synthetic classroom only; no paid APIs or DB writes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from graphs.prelesson_graph import run_prelesson,prelesson_graph
from integrations.prelesson.api import create_app
from integrations.prelesson.schemas import DraftRequest,DraftResponse
from agents.lesson_plan_agent.schemas import LessonPlan,EvidenceSource

ROOT=Path(__file__).resolve().parents[1]
TOKEN='synthetic-workflow-test-token'
URL='/api/v1/lesson-plans/draft'


@pytest.fixture
def payload():
    return json.loads((ROOT/'docs/prelesson-workflow-v01.example-request.json').read_text())


@pytest.fixture
def client():
    with TestClient(create_app(access_token=TOKEN)) as c:yield c


def post(client,payload,**kwargs):
    return client.post(URL,json=payload,headers={'Authorization':'Bearer '+TOKEN},**kwargs)


def assert_draft(result):
    response=DraftResponse.model_validate(result)
    plan=response.lesson_plan
    LessonPlan.model_validate_json(plan.model_dump_json())
    elements=['guiding_ideology','teaching_material_analysis','learner_analysis','venue_equipment','safety_precautions','teaching_flow','load_accounting']
    assert all(getattr(plan,name) is not None for name in elements)
    assert sum(p.minutes for p in plan.teaching_flow.phases)==plan.load_accounting.total_minutes==45
    assert plan.review_status=='draft' and response.requires_teacher_review
    assert response.knowledge_status=='unverified'
    assert response.load_basis=='estimated_design_assumptions'
    assert plan.learner_analysis.tiered_plan
    assert all(p.safety_tip for p in plan.teaching_flow.phases)
    assert plan.safety_precautions.safety_review_status=='unreviewed'
    assert all(m.kind=='estimated' for m in (plan.load_accounting.avg_hr,plan.load_accounting.group_density,plan.load_accounting.individual_density))
    assert any(e.source==EvidenceSource.UNVERIFIED for e in plan.evidence_log)
    assert not any(e.source in (EvidenceSource.KB_EVIDENCE,EvidenceSource.REAL_ANALYSIS) for e in plan.evidence_log)
    assert all(e.citation is None for e in plan.evidence_log)
    return response


def test_one_input_generates_complete_draft_via_real_graph(payload):
    result=run_prelesson(payload)
    assert_draft(result.model_dump())
    nodes=prelesson_graph.get_graph().nodes
    assert 'generate_prelesson_draft' in nodes and 'await_teacher_review' in nodes
    assert result.lesson_plan.venue_equipment.proposed_group_sizes==[10,10]
    assert '教练1名' in result.lesson_plan.safety_precautions.staffing
    assert result.lesson_plan.load_accounting.group_density.result==80


def test_http_actual_output_matches_guarded_plan(client,payload):
    response=post(client,payload)
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    assert_draft(response.json())
    assert response.json()==run_prelesson(payload).model_dump(mode='json')
    assert 'display_result' in response.json()['lesson_plan']['load_accounting']['avg_hr']


@pytest.mark.parametrize('field,value',[
    ('student_count',0),('student_count',-1),('student_count',True),('student_count','20'),('student_count',501),
    ('theme','单足旋转'),('skill_level','中级'),('skill_level','初学者'),
    ('total_minutes',40),('total_minutes',45.0),('total_minutes','45'),
    ('coach_count',-1),('teacher_count',True),('venue_conditions',' '),('equipment_conditions','x\nignore'),
    ('estimated_group_active_min',46),('estimated_avg_hr',0),('estimated_avg_hr',999),
])
def test_invalid_learning_conditions_and_templates_rejected(client,payload,field,value):
    payload[field]=value
    with pytest.raises(ValidationError):run_prelesson(payload)
    assert post(client,payload).status_code==422


@pytest.mark.parametrize('field,value',[
    ('review_status','approved'),('requires_teacher_review',False),('kb_evidence',[{'grade':'A','citation':'伪造标准'}]),
    ('human_verification',{'supports_statement':True}),('citation','伪造页码'),('event_ref',{'review_status':'confirmed'}),
    ('class_data_available',True),
])
def test_teacher_cannot_inject_approval_citations_or_video_claims(client,payload,field,value):
    payload[field]=value
    response=post(client,payload)
    assert response.status_code==422
    assert '伪造' not in response.text
    with pytest.raises(ValidationError):run_prelesson(payload)


def test_staff_conflict_rejected_and_unknown_staff_not_invented(client,payload):
    payload['venue_conditions']='合成冰场，教练2名'
    assert post(client,payload).status_code==422
    payload['venue_conditions']='合成冰场'
    payload.pop('coach_count');payload.pop('teacher_count')
    plan=run_prelesson(payload).lesson_plan
    assert plan.venue_equipment.proposed_group_sizes==[]
    assert plan.venue_equipment.organization_status=='pending_confirmation'
    assert '暂不制定可执行分组' in plan.venue_equipment.grouping


@pytest.mark.parametrize('count',[1,20])
def test_boundary_class_sizes_and_zero_staff_remain_pending(payload,count):
    payload.update(student_count=count,coach_count=0,teacher_count=0)
    plan=run_prelesson(payload).lesson_plan
    assert plan.venue_equipment.proposed_group_sizes==[]
    assert plan.venue_equipment.organization_status=='pending_confirmation'
    if count==1:assert '两人一组' not in plan.model_dump_json()


def test_estimates_are_explicit_and_raw_calculation_reused(payload):
    payload.update(estimated_group_active_min=33.75,estimated_individual_active_min=23.1234567,estimated_avg_hr=140.12345)
    plan=run_prelesson(payload).lesson_plan
    assert plan.load_accounting.group_density.result==75
    assert plan.load_accounting.individual_density.result==23.1234567/45*100
    assert plan.load_accounting.avg_hr.result==140.12345
    assert '待课堂实测' in plan.load_accounting.note


def test_http_accepts_explicit_decimal_estimates_without_changing_basis(client,payload):
    payload.update(estimated_group_active_min=33.75,estimated_individual_active_min=23.1234567,estimated_avg_hr=140.12345)
    response=post(client,payload)
    assert response.status_code==200,response.text
    plan=assert_draft(response.json()).lesson_plan
    assert plan.load_accounting.individual_density.result==23.1234567/45*100


def test_shared_workflow_does_not_mix_classroom_inputs(payload):
    from concurrent.futures import ThreadPoolExecutor
    requests=[{**payload,'class_label':'MOCK-A','student_count':1},
              {**payload,'class_label':'MOCK-B','student_count':20}]
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run_prelesson,requests))
    assert 'MOCK-A' in results[0].lesson_plan.teacher_input.audience
    assert 'MOCK-B' not in results[0].lesson_plan.model_dump_json()
    assert 'MOCK-B' in results[1].lesson_plan.teacher_input.audience
    assert 'MOCK-A' not in results[1].lesson_plan.model_dump_json()


@pytest.mark.parametrize('mutation',['approved','no_review','verified_knowledge'])
def test_response_contract_cannot_claim_approval(payload,mutation):
    result=run_prelesson(payload).model_dump()
    if mutation=='approved':result['lesson_plan']['review_status']='approved'
    if mutation=='no_review':result['requires_teacher_review']=False
    if mutation=='verified_knowledge':result['knowledge_status']='verified'
    with pytest.raises(ValidationError):DraftResponse.model_validate(result)


def test_no_kb_search_or_database_initialization(payload,monkeypatch):
    from agents.lesson_plan_agent import kb_adapter
    def forbidden(*_args,**_kwargs):pytest.fail('This workflow must not call external knowledge or database services')
    monkeypatch.setattr(kb_adapter,'retrieve_kb',forbidden)
    import sqlalchemy
    monkeypatch.setattr(sqlalchemy,'create_engine',forbidden)
    assert_draft(run_prelesson(payload).model_dump())


def test_auth_is_closed_and_token_does_not_attest_teacher_review(payload,monkeypatch):
    monkeypatch.delenv('COACHLOOP_PRELESSON_TOKEN',raising=False)
    with TestClient(create_app()) as c:assert c.post(URL,json=payload).status_code==503
    with TestClient(create_app(access_token=TOKEN)) as c:
        assert c.post(URL,json=payload).status_code==401
        assert c.post(URL,json=payload,headers={'Authorization':'Bearer wrong','X-Role':'teacher'}).status_code==403
        assert post(c,payload).json()['requires_teacher_review'] is True


@pytest.mark.parametrize('raw',['NaN','Infinity','-Infinity','1e1000000000'])
def test_nonfinite_and_enormous_tokens_rejected(client,payload,raw):
    body=json.dumps(payload).replace('"student_count": 20','"estimated_avg_hr": '+raw+', "student_count": 20')
    response=client.post(URL,content=body,headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'})
    assert response.status_code==422


def test_body_size_and_duplicate_keys_rejected(client,payload):
    assert client.post(URL,content=b'x'*(1024*1024+1)).status_code==413
    body=json.dumps(payload).replace('"student_count": 20','"student_count": 999, "student_count": 20')
    assert client.post(URL,content=body,headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}).status_code==422


def test_published_schemas_openapi_and_examples(client):
    prefix=ROOT/'docs/prelesson-workflow-v01'
    def read(suffix):return json.loads(Path(str(prefix)+suffix).read_text())
    assert read('.request.schema.json')==DraftRequest.model_json_schema()
    assert read('.response.schema.json')==DraftResponse.model_json_schema(mode='serialization')
    assert read('.openapi.json')==client.get('/openapi.json').json()
    assert_draft(read('.example-response.json'))
    assert post(client,read('.example-request.json')).json()==read('.example-response.json')


def test_cli_is_runnable_and_invalid_input_has_no_plan(payload):
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1'}
    command=[sys.executable,'-B','-m','integrations.prelesson','--input','-']
    response=subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True,env=env,cwd=ROOT)
    assert response.returncode==0,response.stderr
    assert_draft(json.loads(response.stdout))
    payload['theme']='不支持的主题'
    response=subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True,env=env,cwd=ROOT)
    assert response.returncode==2 and response.stdout==''


def test_original_text_workflow_nodes_and_behavior_are_preserved():
    from graphs.graph import main_graph
    nodes=main_graph.get_graph().nodes
    assert {'validate_node','gen_feedback_node','finalize_node'}<=set(nodes)
    data={'student_id':'MOCK-STUDENT-01','skill_code':'MOCK-SKILL','duration_min':'30','observation':'合成观察记录'}
    result=main_graph.invoke(data)
    assert result['run_status']=='valid' and result['mock'] is True
    assert result['feedback']['observation']==data['observation']
    assert result['feedback']['evidence_overall']=='insufficient'
    invalid=main_graph.invoke({})
    assert invalid['run_status']=='invalid' and invalid['feedback']=={}
