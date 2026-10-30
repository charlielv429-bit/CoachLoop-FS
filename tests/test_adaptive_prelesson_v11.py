"""Synthetic V1.1 regression, differential and adversarial cases; no network."""
import copy
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agents.lesson_plan_agent.adaptive import (AdaptiveRequest, AdaptiveResponse, CATALOG,
    THEMES, generate_adaptive, catalogue)
from integrations.prelesson.console import create_console_app
from integrations.prelesson.adaptive_api import ADAPTIVE, CATALOGUE, create_adaptive_router

BASE = dict(student_count=10, skill_level='零基础', coach_count=2, teacher_count=1,
    usable_area_m2=200, declared_practice_capacity=10, equipment_sets=30,
    safe_waiting_area=True, venue_conditions='合成冰场，可用区待核定', equipment_conditions='合成装备',
    mastered_skills=['safety_equipment'], theme_id='two_foot_glide')
ORIGIN = 'http://127.0.0.1:8767'
HEADERS = {'Origin': ORIGIN, 'X-CoachLoop-Console': '1'}


def result(**updates):
    return generate_adaptive({**BASE, **updates}).model_dump()


def test_catalogue_unique_complete_and_honest():
    assert len(CATALOG) == 24 and len(THEMES) == 24
    required = {'theme_id','name_zh','name_en','supported_levels','prerequisites','goals','key_points',
                'difficulties','practice_progression','candidate_errors','evaluation_indicators',
                'safety_requirements','source','version','verification_status'}
    for t in CATALOG:
        assert required <= t.keys()
        assert t['verification_status'] == 'unverified' and t['source']['reference'] is None
        assert len(t['practice_progression']) == 3
        assert all(p in THEMES for p in t['prerequisites'])
    assert len({tuple(t['practice_progression']) for t in CATALOG}) == 24
    assert len({tuple(t['evaluation_indicators']) for t in CATALOG}) == 24
    out = catalogue(); out[0]['name_zh'] = 'forged'
    assert CATALOG[0]['name_zh'] != 'forged'


@pytest.mark.parametrize('theme', CATALOG, ids=lambda t:t['theme_id'])
def test_every_theme_has_real_distinct_core_and_shared_guards(theme):
    out = result(theme_id=theme['theme_id'],skill_level=theme['min_level'],mastered_skills=theme['prerequisites'])
    assert out['status'] == 'draft_ready'
    plan = out['lesson_plan']; adapt = out['adaptation']
    assert [x['task'] for x in adapt['core_exercises']] == theme['practice_progression']
    assert theme['evaluation_indicators'][0] in adapt['evaluation_indicators']
    assert theme['key_points'] in plan['teaching_material_analysis']['key_points']
    assert sum(x['minutes'] for x in plan['teaching_flow']['phases']) == 45
    assert plan['load_accounting']['total_minutes'] == 45
    assert out['requires_teacher_review'] is True and plan['review_status'] == 'draft'
    assert out['knowledge_status'] == 'unverified'
    assert plan['load_accounting']['avg_hr'] is None
    assert all(e['citation'] is None for e in plan['evidence_log'])
    assert not any(e['source'] in ('kb_evidence','real_analysis') for e in plan['evidence_log'])
    assert plan['venue_equipment']['organization_status'] == 'pending_confirmation'
    assert plan['safety_precautions']['safety_review_status'] == 'unreviewed'


def test_required_four_scenarios_change_structures_not_just_titles():
    a,b,c,d=[result(student_count=n,coach_count=k,skill_level=l) for n,k,l in
        [(10,2,'零基础'),(20,1,'零基础'),(20,2,'初级'),(30,1,'零基础')]]
    aa,bb,cc,dd=[x['adaptation'] for x in (a,b,c,d)]
    assert [x['organization']['rotation_count'] for x in (aa,bb,cc,dd)] == [1,2,2,3]
    assert [len(x['staff_tasks']) for x in (aa,bb,cc,dd)] == [3,2,3,2]
    assert aa['organization']['groups'] != bb['organization']['groups'] != cc['organization']['groups']
    assert aa['goals'] != cc['goals'] and aa['core_exercises'] != cc['core_exercises']
    assert aa['evaluation_indicators'] != cc['evaluation_indicators']
    assert aa['safety_limits'] != bb['safety_limits'] != dd['safety_limits']
    assert aa['staff_tasks'][0]['task'] != cc['staff_tasks'][0]['task']
    active = [x['lesson_plan']['load_accounting']['individual_density']['numerator'] for x in (a,b,d)]
    assert active[0] > active[1] > active[2]
    for out in (a,b,c,d):
        groups=out['adaptation']['organization']['groups']
        assert sum(g['students'] for g in groups)==out['request']['student_count']
        assert all(g['coach'] <= out['request']['coach_count'] for g in groups)


def test_same_class_different_theme_changes_all_core_curriculum_fields():
    a=result(); b=result(theme_id='posture')
    for field in ('goals','core_exercises','evaluation_indicators','safety_limits','staff_tasks'):
        assert a['adaptation'][field] != b['adaptation'][field]


@pytest.mark.parametrize('updates',[
    {'student_count':0},{'student_count':501},{'student_count':True},{'student_count':2.2},
    {'coach_count':-1},{'coach_count':None},{'teacher_count':True},
    {'usable_area_m2':0},{'usable_area_m2':float('nan')},{'usable_area_m2':float('inf')},
    {'total_minutes':44},{'total_minutes':True},{'equipment_sets':-1},
    {'declared_practice_capacity':0},{'safe_waiting_area':'true'},
    {'theme_id':'jump'},{'skill_level':'高级'}, {'mastered_skills':['made_up']},
    {'mastered_skills':['safety_equipment','safety_equipment']},
    {'review_status':'approved'},{'knowledge_status':'verified'},
    {'teacher_notes':'invalid\nnewline'}, {'class_label':'   '},
])
def test_invalid_input_rejected(updates):
    with pytest.raises(ValueError): result(**updates)


@pytest.mark.parametrize('updates',[
    {'coach_count':0}, {'equipment_sets':9}, {'safe_waiting_area':False},
    {'ice_available':False}, {'mastered_skills':[]},
    {'theme_id':'three_turn','skill_level':'零基础'},
    {'student_count':30,'declared_practice_capacity':1},
])
def test_unsafe_or_unsupported_conditions_never_yield_an_ice_implementation(updates):
    out = result(**updates)
    assert out['status']=='needs_confirmation'
    assert out['adaptation']['core_exercises']==[]
    assert out['adaptation']['organization']['groups']==[]
    assert out['adaptation']['staff_tasks']==[]
    assert out['lesson_plan']['load_accounting']['individual_density']['result']==0
    assert '暂缓' in out['lesson_plan']['teaching_flow']['phases'][1]['content']


def test_prerequisites_capacity_age_goal_and_teacher_edits_are_used():
    assert result(mastered_skills=[])['status']=='needs_confirmation'
    small=result(declared_practice_capacity=5)
    large=result(declared_practice_capacity=10)
    assert small['adaptation']['organization']['rotation_count']==2
    assert small['lesson_plan']['load_accounting']['individual_density']['result'] < large['lesson_plan']['load_accounting']['individual_density']['result']
    assert result(age_band='儿童')['adaptation']['safety_limits'] != large['adaptation']['safety_limits']
    edited=result(teacher_goal_edit='先观察方向辨识',teacher_notes='先进行陆地讨论',goal_preference='左右均衡')
    assert '先观察方向辨识' in edited['lesson_plan']['guiding_ideology']['motor_competence']
    assert edited['adaptation']['teacher_notes']=='先进行陆地讨论'
    assert edited['adaptation']['goals']!=large['adaptation']['goals']
    assert edited['adaptation']['evaluation_indicators']!=large['adaptation']['evaluation_indicators']


@pytest.mark.parametrize('field', ['review','citation','load','goals','organization','safety','time','trust'])
def test_export_rejects_mutated_output(field):
    out=generate_adaptive(BASE)
    if field=='review':out.review_status='approved'
    if field=='citation':out.lesson_plan.evidence_log[0].citation='forged standard p1'
    if field=='load':out.lesson_plan.load_accounting.individual_density.denominator=44
    if field=='goals':out.adaptation['goals']=['forged']
    if field=='organization':out.adaptation['organization']['concurrent_students']=100
    if field=='safety':out.lesson_plan.safety_precautions.safety_review_status='approved'
    if field=='time':out.lesson_plan.teaching_flow.phases[0].minutes=10
    if field=='trust':out.requires_teacher_review=False
    with pytest.raises(ValueError):out.model_dump_json()


def test_local_api_security_contract_and_schema():
    with TestClient(create_console_app(),base_url=ORIGIN,client=('127.0.0.1',5678)) as c:
        assert c.post(ADAPTIVE,json=BASE,headers=HEADERS).status_code==401
        c.get('/')
        assert c.get(CATALOGUE).json()['knowledge_status']=='unverified'
        response=c.post(ADAPTIVE,json=BASE,headers=HEADERS)
        assert response.status_code==200
        assert AdaptiveResponse.model_validate(response.json()).model_dump()==response.json()
        for headers in ({}, {**HEADERS,'Origin':'https://invalid.example'}, {**HEADERS,'Authorization':'Bearer forged'}):
            assert c.post(ADAPTIVE,json=BASE,headers=headers).status_code==403
        assert c.post(ADAPTIVE,json={**BASE,'coach_count':False},headers=HEADERS).status_code==422
        assert c.get(ADAPTIVE).status_code==404
        raw=json.dumps(BASE).replace('"student_count": 10','"student_count": 0,"student_count": 10')
        assert c.post(ADAPTIVE,content=raw,headers={**HEADERS,'Content-Type':'application/json'}).status_code==422
        assert c.post(ADAPTIVE,content='x'*(1024*1024+1),headers={**HEADERS,'Content-Type':'application/json'}).status_code==413
    # A mistakenly unguarded mounting is still closed, never relying on self-reported headers.
    unsafe=FastAPI();unsafe.include_router(create_adaptive_router())
    assert TestClient(unsafe).post(ADAPTIVE,json=BASE).status_code==401
    schema=unsafe.openapi()
    assert schema['components']['schemas']['AdaptiveResponse']['properties']['knowledge_status']['const']=='unverified'
    assert schema['components']['schemas']['AdaptiveRequest']['additionalProperties'] is False


def test_teacher_can_edit_core_practice_without_bypassing_safety():
    edited=result(teacher_exercise_edits=['仅进行已确认的分侧观察','','再次口头核对路线'])
    core=edited['adaptation']['core_exercises']
    assert core[0]['task']=='教师修改候选练习（未审核）：仅进行已确认的分侧观察'
    assert core[0]['catalogue_task']==THEMES['two_foot_glide']['practice_progression'][0]
    assert core[1]['task']==core[1]['catalogue_task']
    assert '仅进行已确认的分侧观察' in edited['lesson_plan']['teaching_flow']['phases'][1]['content']
    assert edited['lesson_plan']['review_status']=='draft'
    assert result(coach_count=0,teacher_exercise_edits=['上冰','',''])['adaptation']['core_exercises']==[]
    assert sum(e['active_min_per_student'] for e in core)==pytest.approx(edited['adaptation']['organization']['core_active_min_per_student'])


@pytest.mark.parametrize('updates',[
    {'teacher_exercise_edits':['one']}, {'teacher_exercise_edits':['a\nb','','']},
    {'venue_conditions':'教练10名'}, {'equipment_conditions':'教师20名'},
])
def test_teacher_edits_and_staffing_text_are_validated(updates):
    with pytest.raises(ValueError):result(**updates)


def test_missing_waiting_staff_is_not_silently_invented():
    assert result(student_count=20,teacher_count=0)['status']=='needs_confirmation'
    out=result(teacher_count=0)
    assert out['status']=='draft_ready'
    assert all(t['role']=='coach' for t in out['adaptation']['staff_tasks'])


def test_web_payload_xss_is_preserved_as_text_not_promoted_to_evidence():
    out=result(class_label='<img src=x onerror=alert(1)>',teacher_notes='<script>alert(1)</script>')
    assert out['knowledge_status']=='unverified'
    assert out['adaptation']['teacher_notes']=='<script>alert(1)</script>'
    assert out['lesson_plan']['teacher_input']['audience'].startswith('<img')


def test_partial_last_wave_never_invents_empty_groups():
    out=result(student_count=11,coach_count=10)
    groups=out['adaptation']['organization']['groups']
    assert all(g['students']>0 for g in groups)
    assert sum(g['students'] for g in groups)==11
    assert len([g for g in groups if g['wave']==2])==1


def test_boolean_cannot_replace_integer_in_exported_organization():
    out=generate_adaptive(BASE)
    out.adaptation['organization']['rotation_count']=True
    with pytest.raises(ValueError):out.model_dump_json()


def test_published_schemas_match_code_and_state_local_authentication():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert json.loads((root/'docs/adaptive-prelesson-v11.request.schema.json').read_text())==AdaptiveRequest.model_json_schema()
    assert json.loads((root/'docs/adaptive-prelesson-v11.response.schema.json').read_text())==AdaptiveResponse.model_json_schema(mode='serialization')
    app=FastAPI();app.include_router(create_adaptive_router())
    schema=app.openapi()
    published=json.loads((root/'docs/adaptive-prelesson-v11.openapi.json').read_text())
    assert published['paths']==schema['paths'] and published['components']==schema['components']
    operation=schema['paths'][ADAPTIVE]['post']
    assert operation['security']==[{'LocalConsoleSession':[]}]
    assert {p['name'] for p in operation['parameters']}=={'Origin','X-CoachLoop-Console'}
