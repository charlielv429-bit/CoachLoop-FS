"""Actual authorized page summaries; classroom/teacher inputs remain SYNTHETIC."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from integrations.prelesson.console import create_console_app
from integrations.prelesson.teacher_api import bundled
from integrations.prelesson.textbook_content import assemble, markers_current, ROOT
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.registry import Knowledge
from test_teaching_loop import CONDITIONS, ORIGIN, HEADERS, post


@pytest.fixture
def loaded(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb')
    store.restore_full(bundled())
    yield store
    store.close()


def draft(store,lesson='L05'):
    item=next(i for i in json.loads((ROOT/'docs/course-mvp/course-inventory.json').read_text())['lessons'] if i['lesson']['lesson_id']==lesson)
    return assemble(store,lesson,item['teacher_fields'])


def test_exact_initialization_association_and_restart_without_writes(loaded):
    before=loaded.export_full()
    value=draft(loaded)
    assert [f['fact_id'] for f in value['facts']]==['W91','W92','W93','L39']
    assert {f['knowledge_id'] for f in value['facts']}=={'K010','K018','K012'}
    assert value['facts'][0]['cross_lesson_background']  # K010 remains L04, not relinked.
    assert all(f['status']=='pending' and not f['system_approved'] for f in value['facts'])
    assert all(f['record_kind']=='course_proposal' for f in value['facts'] if f['knowledge_id']=='K018')
    assert '图29' in value['edits']['action_points'] and '单次压步' in value['edits']['practice_steps']
    assert '刀齿' in value['edits']['common_errors']
    assert '五问整体' in value['notice'] and '没有逐条签署' in value['notice']
    assert len(before['archive']['entries'])==27 and len(before['evidence_reports'])==50 and before['review_decisions']==[]
    second=SQLiteRegistry(loaded.directory)
    assert draft(second)==value and second.export_full()==before
    second.close()
    assert loaded.export_full()==before and loaded.teaching_evidence('L05')==[]


@pytest.mark.parametrize('lesson',[f'L0{i}' for i in range(1,9)])
def test_all_lessons_only_use_supported_portions_and_keep_45(loaded,lesson):
    with TestClient(create_console_app(knowledge_store=loaded),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/')
        value=next(d for d in c.get('/api/v4/catalogue').json()['drafts'] if d['lesson_id']==lesson)
        plan=post(c,'/api/v3/plans/draft',dict(lesson_id=lesson,conditions=deepcopy(CONDITIONS),prerequisites_confirmed=False,edits=value['edits']))
        assert [p['minutes'] for p in plan['teaching_flow']['phases']]==[9,29,7]
        assert plan['formal_teaching_evidence']==plan['technical_guidance']==[]
        assert plan['execution_status']=='withheld_pending_specialist_evidence'
        assert '暂缓' in plan['current_teacher_edits']['safety_notes']
        if lesson not in ('L04','L05','L06'):
            assert not value['facts'] and '不外推' in value['gaps'][0]
            assert '压步' not in '\n'.join(value['edits'].values())
            assert '压步' not in '\n'.join(value['proposals'])


def test_empty_database_does_not_claim_bundled_sources(tmp_path):
    store=SQLiteRegistry(tmp_path/'empty')
    value=draft(store)
    assert not value['facts'] and '原PDF91' not in value['edits']['action_points']
    assert any('K010' in gap and '精确匹配' in gap for gap in value['gaps'])
    assert store.export()['entries']==[]
    store.close()


def test_same_id_or_registered_report_is_not_page_verification(loaded,monkeypatch):
    original=loaded.evidence_reports()
    # Same identifier and original-page label, but different evidence bytes: no match.
    changed=deepcopy(original)
    for report in changed:
        if report['knowledge_id']=='K012': report['artifact_sha256']='0'*64
    monkeypatch.setattr(loaded,'evidence_reports',lambda:changed)
    value=draft(loaded)
    assert 'L39' not in {f['fact_id'] for f in value['facts']}
    assert '刀齿' not in value['edits']['common_errors']


def test_new_revision_removes_old_facts_and_blocks_historical_print(loaded):
    with TestClient(create_console_app(knowledge_store=loaded),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/')
        initial=draft(loaded)
        plan=post(c,'/api/v3/plans/draft',dict(lesson_id='L05',conditions=deepcopy(CONDITIONS),prerequisites_confirmed=False,edits=initial['edits']))
        params={'plan_id':plan['plan_id'],'expected_version':1}
        html=c.get('/api/v4/print-plan',params=params)
        assert html.status_code==200 and '原PDF91／印刷77' in html.text and '原PDF39／印刷29' in html.text
        changed={k:loaded.history('K012')[-1][k] for k in Knowledge.model_fields}
        changed.update(version=3,content='SYNTHETIC 修订：支持关系待重新核对')
        loaded.save(Knowledge.model_validate(changed))
        current=draft(loaded)
        assert not markers_current(initial['edits'],current)
        assert c.get('/api/v4/print-plan',params=params).status_code==409
        assert 'L39' not in {f['fact_id'] for f in current['facts']}
        assert [e['version'] for e in loaded.history('K012')]==[1,2,3]
        assert loaded.teaching_evidence('L05')==[]


def test_missing_original_report_and_rejected_entry_fail_closed(loaded,monkeypatch):
    original=loaded.evidence_reports()
    monkeypatch.setattr(loaded,'evidence_reports',lambda:[r for r in original if r['knowledge_id']!='K018'])
    value=draft(loaded)
    assert not {'W92','W93'} & {f['fact_id'] for f in value['facts']}
    entries=loaded.search()
    next(e for e in entries if e['knowledge_id']=='K010')['specialist_review_status']='rejected'
    monkeypatch.setattr(loaded,'search',lambda:entries)
    assert 'W91' not in {f['fact_id'] for f in draft(loaded)['facts']}


def test_teacher_edit_print_and_json_keep_pending_and_escape(loaded):
    with TestClient(create_console_app(knowledge_store=loaded),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/')
        value=draft(loaded)
        plan=post(c,'/api/v3/plans/draft',dict(lesson_id='L05',conditions=deepcopy(CONDITIONS),prerequisites_confirmed=False,edits=value['edits']))
        edited=post(c,'/api/v3/plans/edit',{'plan_id':plan['plan_id'],'expected_version':1,'goal_draft':'SYNTHETIC：教师待审目标 & 修改'})
        assert edited['version']==2 and edited['formal_teaching_evidence']==[]
        assert c.post('/api/v3/plans/edit',json={'plan_id':plan['plan_id'],'expected_version':2,'specialist_review_status':'approved'},headers=HEADERS).status_code==422
        assert c.post('/api/v3/plans/edit',json={'plan_id':plan['plan_id'],'expected_version':2,'action_points':'<script>alert(1)</script>'},headers=HEADERS).status_code==422
        html=c.get('/api/v4/print-plan',params={'plan_id':plan['plan_id'],'expected_version':2})
        assert html.status_code==200 and '&amp;' in html.text and '教材直接支持的事实' in html.text
        assert '缺少正式专项依据' not in html.text and '非原文' in html.text
        exported=c.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']})
        assert exported.status_code==200
        assert '原PDF91' in exported.text and 'pending' in exported.text
