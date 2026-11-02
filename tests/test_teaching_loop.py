"""End-to-end local connector tests. All observations are explicitly SYNTHETIC."""
from copy import deepcopy
from uuid import uuid4
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from integrations.prelesson.console import create_console_app
from integrations.teaching_loop.service import BASE
from integrations.local_video.service import VideoStore, COOKIE as VIDEO_COOKIE
from integrations.curriculum_v3.planning import PLAN_COOKIE
from integrations.curriculum_v3.registry import Registry
from integrations.curriculum_v3.persistence import SQLiteRegistry
from test_l05_application import load_candidates

ORIGIN='http://127.0.0.1:8767'
HEADERS={'Origin':ORIGIN,'X-CoachLoop-Console':'1'}
CONDITIONS=dict(student_count=20,skill_level='初级',coach_count=2,teacher_count=1,usable_area_m2=200.,declared_practice_capacity=10,equipment_sets=20,safe_waiting_area=True,venue_conditions='合成场地',equipment_conditions='合成装备')


@pytest.fixture
def client():
    with TestClient(create_console_app(),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/');yield c


def post(c,path,body):
    r=c.post(path,json=body,headers=HEADERS)
    assert r.status_code==200,r.text
    return r.json()


def setup(c,lesson='L05'):
    plan=post(c,'/api/v3/plans/draft',dict(lesson_id=lesson,prerequisites_confirmed=False,conditions=deepcopy(CONDITIONS)))
    job=post(c,BASE+'/demo-analysis',{'synthetic_demo':True})
    body=dict(plan_id=plan['plan_id'],expected_plan_version=1,job_id=job['job_id'],learner_code='ANON-001',observation='合成测试：只报告候选变化，尚需核实拍摄条件。',practice_task='合成任务：先核对观察条件和既有教材，专项与安全未确认前不实操。')
    return plan,job,body


def confirmation(value):
    return dict(loop_id=value['loop_id'],expected_version=value['version'],expected_evidence_digest=value['current_evidence_digest'],acknowledged=True)


def edit(value,**updates):
    return {**{k:value[k] for k in ('loop_id','observation','practice_task')},'expected_version':value['version'],'expected_evidence_digest':value['current_evidence_digest'],**updates}


def export(c,key):
    r=c.get(BASE+'/export',params={'loop_id':key});assert r.status_code==200,r.text;return r.json()


def test_full_l05_loop_draft_explicit_confirmation_edit_and_export(client):
    p,j,body=setup(client)
    v=post(client,BASE+'/link',body)
    assert v['is_mock'] and v['analysis']['synthetic_demo'] and v['data_origin']=='synthetic_keypoints_demo'
    assert v['feedback_review_status']=='draft' and not v['confirmation_current']
    assert len(v['analysis']['candidate_changes'])==1 and len(v['plan']['l05_teaching_design']['areas'])==7
    assert [p['minutes'] for p in v['plan']['teaching_flow']['phases']]==[9,29,7]
    # Event confirmation is not feedback confirmation.
    event=v['analysis']['candidate_changes'][0]
    post(client,'/api/v2/video/review',dict(job_id=j['job_id'],event_id=event['event_id'],status='confirmed',note='合成观察，非技术错误',expected_sequence=0,request_id=uuid4().hex))
    stale=client.post(BASE+'/confirm',json=confirmation(v),headers=HEADERS)
    assert stale.status_code==409
    v=export(client,v['loop_id']);assert v['feedback_review_status']=='draft'
    v=post(client,BASE+'/edit',edit(v))
    v=post(client,BASE+'/confirm',confirmation(v))
    assert v['feedback_review_status']=='locally_confirmed_unverified' and v['confirmation_current']
    assert v['authenticated_teacher'] is False and v['specialist_review_status']=='pending'
    assert v['technical_error_assessment']=='not_assessed' and v['trusted_observations']==[]
    assert v['base_feedback']['review_status']=='draft' and v['base_feedback']['authenticated_coach'] is False
    full=export(client,v['loop_id'])
    assert len(full['history'])==3 and full['history'][-1]['operation']=='locally_confirmed'
    assert full['analysis']['candidate_changes'][0]['local_review_history'][0]['reviewed_at']
    raw=json.dumps(full,ensure_ascii=False)
    assert client.cookies.get(VIDEO_COOKIE) not in raw and client.cookies.get(PLAN_COOKIE) not in raw
    assert 'keypoints' not in full and 'video_path' not in raw and '_owner' not in raw
    changed=post(client,BASE+'/edit',edit(v,observation='模拟新文字：教师自称已审核，仍不认证。'))
    assert changed['feedback_review_status']=='draft' and changed['confirmation'] is None
    assert client.post(BASE+'/edit',json=edit(v),headers=HEADERS).status_code==409


def test_blank_or_unacknowledged_confirmation_cannot_pass(client):
    _,_,body=setup(client);body['observation']=''
    v=post(client,BASE+'/link',body)
    assert client.post(BASE+'/confirm',json=confirmation(v),headers=HEADERS).status_code==409
    v=post(client,BASE+'/edit',edit(v,observation='合成测试观察'))
    assert client.post(BASE+'/confirm',json={**confirmation(v),'acknowledged':False},headers=HEADERS).status_code==409
    assert client.post(BASE+'/confirm',json={**confirmation(v),'acknowledged':1},headers=HEADERS).status_code==422


def test_plan_and_event_changes_invalidate_prior_confirmation(client):
    p,j,b=setup(client);v=post(client,BASE+'/link',b);v=post(client,BASE+'/confirm',confirmation(v))
    post(client,'/api/v3/plans/edit',dict(plan_id=p['plan_id'],expected_version=1,goal_draft='合成更改目标'))
    stale=export(client,v['loop_id'])
    assert stale['evidence_changed'] and not stale['confirmation_current'] and stale['feedback_review_status']=='draft'
    assert stale['plan_version']==1 and stale['current_plan_version']==2
    v=post(client,BASE+'/confirm',confirmation(stale))
    ev=v['analysis']['candidate_changes'][0]
    post(client,'/api/v2/video/review',dict(job_id=j['job_id'],event_id=ev['event_id'],status='uncertain',note='合成证据变化',expected_sequence=0,request_id=uuid4().hex))
    stale=export(client,v['loop_id']);assert not stale['confirmation_current']
    assert stale['confirmation']['verification']=='local_unverified'


def test_cross_browser_and_single_cookie_mix_cannot_read_or_change(client):
    _,j,b=setup(client);v=post(client,BASE+'/link',b)
    other=TestClient(client.app,base_url=ORIGIN,client=('127.0.0.1',4001));other.get('/')
    assert other.get(BASE+'/current').json()=={'records':[]}
    assert other.get(BASE+'/export',params={'loop_id':v['loop_id']}).status_code==404
    assert other.post(BASE+'/edit',json=edit(v),headers=HEADERS).status_code==404
    assert other.post(BASE+'/confirm',json=confirmation(v),headers=HEADERS).status_code==404
    assert other.post(BASE+'/delete',json={'loop_id':v['loop_id']},headers=HEADERS).status_code==404
    # Even a copied plan cookie does not grant the video's private ownership.
    other.cookies.set(PLAN_COOKIE,client.cookies.get(PLAN_COOKIE))
    assert other.get(BASE+'/export',params={'loop_id':v['loop_id']}).status_code==404
    assert other.post(BASE+'/link',json=b,headers=HEADERS).status_code==404
    assert other.get(BASE+'/current').json()=={'records':[]}


@pytest.mark.parametrize('changes',[{'learner_code':'真实姓名'},{'observation':'<script>alert(1)</script>'},
 {'practice_task':'bad\x00text'},{'observation':'x'*1501},{'authenticated_teacher':True},
 {'feedback_review_status':'approved'},{'reviewed_by':'教练'},{'specialist_review_status':'approved'}])
def test_invalid_text_and_forged_authority_are_rejected(client,changes):
    _,_,b=setup(client)
    assert client.post(BASE+'/link',json={**b,**changes},headers=HEADERS).status_code==422
    assert client.get(BASE+'/current').json()=={'records':[]}


@pytest.mark.parametrize('value',[False,1,'true'])
def test_demo_ack_must_be_exact_true(client,value):
    assert client.post(BASE+'/demo-analysis',json={'synthetic_demo':value},headers=HEADERS).status_code==422


def test_l05_only_and_unsaved_plan_version_conflict(client):
    _,_,b=setup(client,lesson='L04')
    assert client.post(BASE+'/link',json=b,headers=HEADERS).status_code==409
    p=post(client,'/api/v3/plans/draft',dict(lesson_id='L05',conditions=deepcopy(CONDITIONS)))
    assert client.post(BASE+'/link',json={**b,'plan_id':p['plan_id'],'expected_plan_version':2},headers=HEADERS).status_code==409


def test_delete_video_and_expiry_remove_private_access(client):
    _,j,b=setup(client);v=post(client,BASE+'/link',b)
    post(client,'/api/v2/video/delete',{'job_id':j['job_id']})
    assert client.get(BASE+'/export',params={'loop_id':v['loop_id']}).status_code==404
    assert client.get(BASE+'/current').json()=={'records':[]}
    _,j,b=setup(client);v=post(client,BASE+'/link',b)
    store=client.app.state.video_store;token=client.cookies.get(VIDEO_COOKIE)
    store.sessions[token]['expires']=store.clock()-1
    assert client.get(BASE+'/export',params={'loop_id':v['loop_id']}).status_code==401


def test_loop_delete_history_and_reload_list(client):
    _,_,b=setup(client);v=post(client,BASE+'/link',b)
    assert client.get(BASE+'/current').json()['records'][0]['loop_id']==v['loop_id']
    assert client.get(BASE+'/history',params={'loop_id':v['loop_id']}).json()['history'][0]['operation']=='linked'
    post(client,BASE+'/delete',{'loop_id':v['loop_id']})
    assert client.get(BASE+'/export',params={'loop_id':v['loop_id']}).status_code==404


def test_all_loop_routes_keep_local_csrf_and_no_main_or_classroom_access(client):
    for suffix,body in [('demo-analysis',{'synthetic_demo':True}),('link',{}),('edit',{}),('confirm',{}),('delete',{})]:
        assert client.post(BASE+'/'+suffix,json=body).status_code==403
        assert client.post(BASE+'/'+suffix,json=body,headers={**HEADERS,'Origin':'https://evil.example'}).status_code==403
        assert client.post(BASE+'/'+suffix,json=body,headers={**HEADERS,'X-Forwarded-For':'127.0.0.1'}).status_code==403
    client.cookies.delete(PLAN_COOKIE)
    assert client.get(BASE+'/current').status_code==401


def test_shared_kb_unchanged_and_knowledge_change_invalidates_confirmation(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');load_candidates(store);before=store.export_full()
    with TestClient(create_console_app(knowledge_store=store),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/');_,_,b=setup(c);v=post(c,BASE+'/link',b);v=post(c,BASE+'/confirm',confirmation(v))
        assert store.export_full()==before
        from integrations.curriculum_v3.registry import Knowledge
        old=next(e for e in store.export()['entries'] if e['knowledge_id']=='K012')
        store.save(Knowledge(**{**old,'version':2,'content':'明确合成知识更新，仅测试临时库'}))
        current=export(c,v['loop_id'])
        assert current['feedback_review_status']=='draft' and current['evidence_changed']
        assert current['plan']['formal_teaching_evidence']==[]


def test_task_ttl_and_service_shutdown_clear_records():
    app=create_console_app()
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',4000)) as client:
        client.get('/')
        _,j,b=setup(client);v=post(client,BASE+'/link',b)
        store=app.state.video_store
        store.jobs[j['job_id']].created=store.clock()-1201
        assert client.get(BASE+'/export',params={'loop_id':v['loop_id']}).status_code==404
        assert app.state.teaching_loops.records=={}
        _,_,b=setup(client);post(client,BASE+'/link',b)
        assert app.state.teaching_loops.records
    assert app.state.teaching_loops.records=={} and store.jobs=={} and store.closed


def test_capacity_refusal_keeps_saved_private_history(client):
    _,_,b=setup(client);v=post(client,BASE+'/link',b)
    for i in range(99):v=post(client,BASE+'/edit',edit(v,observation=f'合成容量测试观察{i}'))
    assert v['version']==100
    assert client.post(BASE+'/edit',json=edit(v),headers=HEADERS).status_code==409
    result=export(client,v['loop_id'])
    assert result['version']==100 and len(result['history'])==100


def test_classroom_cannot_access_loop_api_or_script():
    from test_classroom_tunnel import CODE, ORIGIN as site, HEADERS as headers, http_origin, login
    from integrations.prelesson.classroom import DemoState, create_classroom_app
    state=DemoState(CODE);state.pin(site)
    with TestClient(http_origin(create_classroom_app(state)),base_url=site,headers={'X-Forwarded-Proto':'https'},client=('127.0.0.1',54321)) as c:
        login(c)
        for path in ('/teaching-loop.js',BASE+'/current',BASE+'/export',BASE+'/history'):
            assert c.get(path).status_code==404
        for path in ('demo-analysis','link','edit','confirm','delete'):
            assert c.post(BASE+'/'+path,json={},headers=headers).status_code==404


from test_prelesson_route import isolated_main, main_client


def test_production_main_does_not_mount_private_loop(main_client):
    assert main_client.get(BASE+'/current').status_code==404
    assert main_client.post(BASE+'/demo-analysis',json={'synthetic_demo':True}).status_code==404
    assert main_client.get('/teaching-loop.js').status_code==404


def test_synthetic_review_revocation_returns_confirmed_loop_to_draft(tmp_path):
    from test_p32_reviews import setup_case, approve
    from integrations.curriculum_v3.review import ReviewDecision, seal
    registry,entry,decision,key,keyfile,files,reports=setup_case(tmp_path)
    approve(registry,decision,key,files) # SYNTHETIC operator and evidence, never real specialist approval.
    with TestClient(create_console_app(knowledge_store=registry),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/');_,_,body=setup(c)
        v=post(c,BASE+'/link',body);v=post(c,BASE+'/confirm',confirmation(v))
        assert v['confirmation_current']
        revoked=ReviewDecision(**{**decision.model_dump(),'review_id':'SYNTHETIC_LOOP_REVOKE','decision':'revoked'})
        registry.apply_decision(seal(revoked.model_dump(),key))
        current=export(c,v['loop_id'])
        assert current['feedback_review_status']=='draft' and not current['confirmation_current']
        assert current['plan']['formal_teaching_evidence']==current['plan']['technical_guidance']==[]
