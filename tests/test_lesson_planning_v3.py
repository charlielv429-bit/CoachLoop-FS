"""Synthetic planning and knowledge only; no professional skating claims."""
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from integrations.prelesson.console import create_console_app
from integrations.curriculum_v3.planning import LessonRequest, build_framework, PlanStore
from integrations.curriculum_v3.registry import Registry, RegistryError, Knowledge
from agents.lesson_plan_agent.adaptive import catalogue

ORIGIN='http://127.0.0.1:8767'
HEADERS={'Origin':ORIGIN,'X-CoachLoop-Console':'1'}
CONDITIONS=dict(student_count=20, skill_level='初级', coach_count=2, teacher_count=1,
    usable_area_m2=200., declared_practice_capacity=10,equipment_sets=20,
    safe_waiting_area=True,ice_available=True,venue_conditions='合成场地',equipment_conditions='合成装备')


def payload(**extra):
    return dict(lesson_id='L05',conditions=deepcopy(CONDITIONS),prerequisites_confirmed=True,**extra)


@pytest.fixture
def client():
    with TestClient(create_console_app(),base_url=ORIGIN,client=('127.0.0.1',50000)) as c:
        c.get('/')
        yield c


def post(client,path,body):
    return client.post('/api/v3/plans/'+path,json=body,headers=HEADERS)


@pytest.mark.parametrize('lesson_id',[f'L0{i}' for i in range(1,9)])
def test_empty_registry_all_lessons_generate_safe_45_minutes(client,lesson_id):
    body=payload();body['lesson_id']=lesson_id
    response=post(client,'draft',body)
    assert response.status_code==200,response.text
    plan=response.json()
    assert plan['mode']=='lesson' and plan['lesson']['lesson_id']==lesson_id
    assert sum(p['minutes'] for p in plan['teaching_flow']['phases'])==45
    assert [p['minutes'] for p in plan['teaching_flow']['phases']]==[9,29,7]
    assert plan['knowledge_inventory']==plan['formal_teaching_evidence']==plan['technical_guidance']==[]
    assert '待审核教案框架' in plan['title'] and plan['requires_teacher_review']
    assert plan['execution_status']=='withheld_pending_specialist_evidence'
    assert plan['missing_materials'] and plan['teacher_review_checklist'] and plan['differentiation']
    org=plan['organization']
    assert org['wave_sizes']==[10,10] and sum(g['students'] for g in org['groups'])==20
    assert plan['load_accounting']['individual_density']['result']==pytest.approx(18/45*100)
    assert plan['load_accounting']['avg_hr'] is None


@pytest.mark.parametrize('update',[
 {'coach_count':0}, {'equipment_sets':19}, {'safe_waiting_area':False},
 {'ice_available':False}, {'teacher_count':0}, {'declared_practice_capacity':1,'student_count':25,'equipment_sets':25},
])
def test_resource_holds_are_preserved(client,update):
    body=payload();body['conditions'].update(update)
    result=post(client,'draft',body).json()
    assert result['organization']['status']=='withheld'
    assert result['organization']['reasons'] and result['organization']['groups']==[]
    assert result['load_accounting']['individual_density']['numerator']==0
    assert sum(x['minutes'] for x in result['teaching_flow']['phases'])==45


def test_unknown_prerequisites_hold_without_legacy_mapping(client):
    body=payload();body['prerequisites_confirmed']=False
    plan=post(client,'draft',body).json()
    assert plan['organization']['status']=='withheld'
    assert any('先修' in reason for reason in plan['organization']['reasons'])
    assert 'theme_id' not in plan and 'mastered_skills' not in plan


def test_only_real_linked_versions_are_inventory_not_technical_guidance(client):
    # Explicit synthetic reference. Not a claim to real professional knowledge.
    entry=dict(knowledge_id='SYNTHETIC_ONLY',category='KB-S',title='模拟专项资料',content='模拟动作指令不应传播到框架',
       lesson_ids=['L05'],source_id='SYNTHETIC_SOURCE',source_title='模拟来源',source_locator='模拟页码1',
       source_verification_status='submitted',specialist_review_status='requested',version=1)
    response=client.post('/api/v3/knowledge',json=entry,headers=HEADERS)
    assert response.status_code==200
    plan=post(client,'draft',payload()).json()
    item=plan['knowledge_inventory'][0]
    assert item['knowledge_id']==entry['knowledge_id'] and item['version']==1
    assert item['source_id']==entry['source_id'] and item['source_locator']==entry['source_locator']
    assert item['source_registered'] and not item['source_content_verified'] and not item['specialist_verified']
    assert item['usage']=='metadata_only_not_teaching_guidance'
    assert entry['content'] not in json.dumps(plan,ensure_ascii=False)
    assert plan['formal_teaching_evidence']==[]
    unrelated=payload();unrelated['lesson_id']='L04'
    assert post(client,'draft',unrelated).json()['knowledge_inventory']==[]
    # Later knowledge edits do not rewrite a previously exported snapshot.
    entry.update(version=2,source_locator='模拟页码2')
    assert client.post('/api/v3/knowledge',json=entry,headers=HEADERS).status_code==200
    exported=client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()
    assert exported['knowledge_inventory'][0]['source_locator']=='模拟页码1'


def test_teacher_edits_history_export_and_conflict(client):
    plan=post(client,'draft',payload()).json()
    edits=dict(plan_id=plan['plan_id'],expected_version=1,goal_draft='模拟教师目标',organization_note='模拟组织修改',resource_note='模拟资源备注')
    updated=post(client,'edit',edits)
    assert updated.status_code==200,updated.text
    result=updated.json()
    assert result['effective_goal_draft']=={'text':'模拟教师目标','status':'teacher_pending_review'}
    assert result['version']==2 and result['current_teacher_edits']['goal_draft']=='模拟教师目标'
    assert len(result['teacher_edits'])==2 and result['teacher_edits'][-1]['review_status']=='pending_review'
    for key in ('execution_status','technical_guidance','formal_teaching_evidence','organization','teaching_flow','conditions'):
        assert result[key]==plan[key]
    assert post(client,'edit',edits).status_code==409
    export=client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']})
    assert export.json()==result
    history=client.get('/api/v3/plans/history',params={'plan_id':plan['plan_id']}).json()['versions']
    assert [p['version'] for p in history]==[1,2] and history[0]==plan
    assert client.get('/api/v3/plans/export?plan_id='+'0'*32).status_code==404


@pytest.mark.parametrize('field,value',[
 ('theme_id','forward_crossovers'),('lesson_id','two_foot_glide'),('review_status','approved'),
 ('source_content_verified',True),('technical_guidance',['伪造动作']),('formal_teaching_evidence',['fake']),
])
def test_request_cannot_supply_legacy_ids_or_certification(client,field,value):
    body=payload();body[field]=value
    assert post(client,'draft',body).status_code==422


@pytest.mark.parametrize('extra',[
 {'specialist_review_status':'approved'},{'review_status':'approved'}, {'goal_draft':'<script>bad</script>'},
 {'resource_note':'\x00bad'},{'conditions':CONDITIONS}, {'expected_version':True},
])
def test_edits_cannot_change_protection(client,extra):
    plan=post(client,'draft',payload()).json()
    edit=dict(plan_id=plan['plan_id'],expected_version=1,**{k:v for k,v in extra.items() if k!='expected_version'})
    if 'expected_version' in extra:edit['expected_version']=extra['expected_version']
    assert post(client,'edit',edit).status_code==422
    assert client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()==plan


def test_local_boundary_and_lifecycle():
    app=create_console_app()
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50001)) as c:
        assert post(c,'draft',payload()).status_code==401
        assert c.get('/api/v3/plans/export?plan_id='+'0'*32).status_code==401
        c.get('/')
        assert c.post('/api/v3/plans/draft',json=payload()).status_code==403
        assert c.post('/api/v3/plans/draft',json=payload(),headers={**HEADERS,'Origin':'https://evil.invalid'}).status_code==403
        assert post(c,'draft',payload()).status_code==200
    assert app.state.lesson_plans._plans=={}


def test_plan_capacity_is_atomic_and_returns_safe_error():
    store=PlanStore();registry=Registry();request=LessonRequest(**payload())
    for _ in range(100):store.create(request,registry)
    with pytest.raises(RegistryError):store.create(request,registry)
    assert sum(map(len,store._plans.values()))==100


def test_legacy_topics_still_24_and_dont_accept_lesson_ids(client):
    assert len(catalogue())==24
    body={**CONDITIONS,'theme_id':'L05'}
    assert client.post('/api/v1/lesson-plans/adaptive-draft',json=body,headers=HEADERS).status_code==422
    body['theme_id']='two_foot_glide'
    body['skill_level']='零基础';body['mastered_skills']=['safety_equipment']
    assert client.post('/api/v1/lesson-plans/adaptive-draft',json=body,headers=HEADERS).status_code==200


def test_json_and_static_safety(client):
    raw=json.dumps(payload()).replace('"lesson_id": "L05"','"lesson_id":"L04","lesson_id":"L05"')
    assert client.post('/api/v3/plans/draft',content=raw,headers={**HEADERS,'Content-Type':'application/json'}).status_code==422
    assert client.post('/api/v3/plans/draft',content='x'*(1024*1024+1),headers={**HEADERS,'Content-Type':'application/json'}).status_code==413
    script=client.get('/lesson-planning.js').text
    assert 'textContent' in script
    assert all(x not in script for x in ('innerHTML','localStorage','document.cookie','insertAdjacentHTML'))
