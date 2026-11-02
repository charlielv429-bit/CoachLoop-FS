"""L05 application tests: candidate package is real input; all approvals are SYNTHETIC."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_p32_reviews import setup_case, approve, request as review_request
from integrations.curriculum_v3.registry import Registry, Archive, Knowledge
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.review import EvidenceBundle, ReviewDecision, seal
from integrations.curriculum_v3.planning import LessonRequest, PlanStore, guard_current_evidence
from integrations.curriculum_v3.l05 import AREA_SPECS
from integrations.prelesson.console import create_console_app

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='http://127.0.0.1:8767'
HEADERS={'Origin':ORIGIN,'X-CoachLoop-Console':'1'}
CONDITIONS=dict(student_count=20,skill_level='初级',coach_count=2,teacher_count=1,usable_area_m2=200.,declared_practice_capacity=10,equipment_sets=20,safe_waiting_area=True,venue_conditions='合成场地',equipment_conditions='合成装备')


def body():return dict(lesson_id='L05',conditions=deepcopy(CONDITIONS),prerequisites_confirmed=True)


def load_candidates(store):
    archive=Archive.model_validate(json.loads((ROOT/'docs/p32-input/p32-knowledge-import.json').read_text()))
    store.import_archive(archive)
    reports=EvidenceBundle.model_validate(json.loads((ROOT/'docs/p32-input/p32-evidence-reports.json').read_text()))
    store.save_reports(reports.reports)


def client_for(store):return TestClient(create_console_app(knowledge_store=store),base_url=ORIGIN,client=('127.0.0.1',55300))


def test_real_candidates_split_sources_and_conflicts_without_approval(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');load_candidates(store);before=store.export_full()
    with client_for(store) as client:
        client.get('/')
        response=client.post('/api/v3/plans/draft',json=body(),headers=HEADERS)
        assert response.status_code==200,response.text
        plan=response.json();design=plan['l05_teaching_design']
        assert set(design['areas'])==set(AREA_SPECS) and len(design['areas'])==7
        assert [x['minutes'] for x in plan['teaching_flow']['phases']]==[9,29,7]
        groups=design['material_groups']
        assert [x['knowledge_id'] for x in groups['specialist_knowledge']]==['K011','K012']
        assert [x['knowledge_id'] for x in groups['teaching_progression']]==['K018']
        assert [x['knowledge_id'] for x in groups['evaluation_suggestions']]==['K019']
        assert groups['teaching_progression'][0]['content_kind']=='course_proposal'
        assert all(not area['is_formal_guidance'] and area['review_status']=='pending_review' for area in design['areas'].values())
        assert plan['technical_guidance']==plan['formal_teaching_evidence']==design['reviewed_citations']==[]
        assert {x['knowledge_id'] for x in design['location_checks']}=={'K010','K011','K018'}
        assert all(x['source_conflict_status']=='unresolved' for x in design['location_checks'])
        for cards in groups.values():
            for card in cards:
                assert card['knowledge_id'] and card['source_id'] and card['source_locator']
                assert '不是' in card['label'] and card['candidate_text']
        assert store.export_full()==before


def test_teacher_edits_all_seven_fields_versioned_and_exported():
    with client_for(Registry()) as client:
        client.get('/')
        plan=client.post('/api/v3/plans/draft',json=body(),headers=HEADERS).json()
        values={key:'模拟教师填写（非真实审核）：'+label for key,(label,_) in AREA_SPECS.items()}
        result=client.post('/api/v3/plans/edit',json={**values,'plan_id':plan['plan_id'],'expected_version':1},headers=HEADERS)
        assert result.status_code==200,result.text
        updated=result.json()
        for key,value in values.items():
            assert updated['l05_teaching_design']['areas'][key]['text']==value
            assert updated['l05_teaching_design']['areas'][key]['origin']=='teacher_unverified'
        for key in ('teaching_flow','organization','execution_status','technical_guidance','formal_teaching_evidence'):
            assert updated[key]==plan[key]
        assert updated['version']==2 and updated['review_status']=='pending_review'
        assert client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()==updated
        history=client.get('/api/v3/plans/history',params={'plan_id':plan['plan_id']}).json()['versions']
        assert [v['version'] for v in history]==[1,2]
        assert history[0]['l05_teaching_design']['areas']['action_points']['origin']=='framework_placeholder'
        assert history[1]['teacher_edits'][-1]['values']['action_points']==values['action_points']
        assert client.post('/api/v3/plans/edit',json={**values,'plan_id':plan['plan_id'],'expected_version':1},headers=HEADERS).status_code==409


@pytest.mark.parametrize('key',list(AREA_SPECS))
def test_new_teacher_fields_plain_text_and_cannot_approve(key):
    with client_for(Registry()) as client:
        client.get('/')
        plan=client.post('/api/v3/plans/draft',json=body(),headers=HEADERS).json()
        for extra in ({key:'<script>alert(1)</script>'},{key:'\x00invalid'},{key:{'review_status':'approved'}},{key:'模拟文字','review_status':'approved'}):
            payload={**extra,'plan_id':plan['plan_id'],'expected_version':1}
            assert client.post('/api/v3/plans/edit',json=payload,headers=HEADERS).status_code==422
        assert client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()['version']==1


def test_resource_holds_and_other_lessons_unchanged():
    with client_for(Registry()) as client:
        client.get('/')
        payload=body();payload['conditions']['coach_count']=0
        plan=client.post('/api/v3/plans/draft',json=payload,headers=HEADERS).json()
        edited=client.post('/api/v3/plans/edit',json={'plan_id':plan['plan_id'],'expected_version':1,'safety_notes':'模拟教师自报可以上冰（未经审核）'},headers=HEADERS).json()
        assert edited['organization']['status']=='withheld' and edited['organization']['groups']==[]
        assert edited['technical_guidance']==[] and edited['execution_status'].startswith('withheld')
        for i in (1,2,3,4,6,7,8):
            payload=body();payload['lesson_id']=f'L0{i}'
            result=client.post('/api/v3/plans/draft',json=payload,headers=HEADERS).json()
            assert 'l05_teaching_design' not in result
            assert sum(p['minutes'] for p in result['teaching_flow']['phases'])==45


def test_review_revocation_updates_l05_cards_history_and_export(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    approve(store,record,key,files)
    with client_for(store) as client:
        client.get('/')
        plan=client.post('/api/v3/plans/draft',json=review_request().model_dump(),headers=HEADERS).json()
        design=plan['l05_teaching_design']
        assert design['reviewed_citations'][0]['source_id']==entry.source_id
        assert design['material_groups']['specialist_knowledge'][0]['citation_status']=='reviewed_for_draft_only'
        revoked=ReviewDecision(**{**record.model_dump(),'review_id':'SYNTHETIC_P33_REVOKE','decision':'revoked'})
        store.apply_decision(seal(revoked.model_dump(),key))
        exported=client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()
        assert exported['l05_teaching_design']['reviewed_citations']==[]
        card=exported['l05_teaching_design']['material_groups']['specialist_knowledge'][0]
        assert card['citation_status']=='withdrawn_pending_regeneration' and card['candidate_text']==''
        history=client.get('/api/v3/plans/history',params={'plan_id':plan['plan_id']}).json()
        assert history['versions'][0]['l05_teaching_design']['reviewed_citations']==[]


def test_candidate_version_change_removes_stale_quote_without_upgrading(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');load_candidates(store)
    with client_for(store) as client:
        client.get('/')
        plan=client.post('/api/v3/plans/draft',json=body(),headers=HEADERS).json()
        old=next(x for x in store.export()['entries'] if x['knowledge_id']=='K012')
        store.save(Knowledge(**{**old,'version':2,'content':'模拟测试修改，仅用于临时库'}))
        exported=client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()
        card=next(x for x in exported['l05_teaching_design']['material_groups']['specialist_knowledge'] if x['knowledge_id']=='K012')
        assert card['citation_status']=='superseded_or_unlinked' and card['candidate_text']==''
        assert exported['formal_teaching_evidence']==[]
        assert exported['evidence_status']=='requires_regeneration_after_knowledge_change'


def test_l05_new_notes_remain_private_to_browser():
    with client_for(Registry()) as client:
        client.get('/')
        payload=body();payload['edits']={'action_points':'SYNTHETIC_PRIVATE_P33_NOTE'}
        plan=client.post('/api/v3/plans/draft',json=payload,headers=HEADERS).json()
        other=TestClient(client.app,base_url=ORIGIN,client=('127.0.0.1',55301));other.get('/')
        response=other.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']})
        assert response.status_code==404 and 'SYNTHETIC_PRIVATE_P33_NOTE' not in response.text
        assert 'SYNTHETIC_PRIVATE_P33_NOTE' not in other.get('/api/v3/export').text
