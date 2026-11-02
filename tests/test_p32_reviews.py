"""All approvals/identities/artifacts below are explicitly synthetic, never real teaching evidence."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from integrations.curriculum_v3.registry import Knowledge, Archive, RegistryError
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.review import EvidenceReport, ReviewDecision, seal, knowledge_digest
from integrations.curriculum_v3.candidates import convert
from integrations.curriculum_v3.planning import LessonRequest, build_framework
from integrations.prelesson.console import create_console_app

ROOT=Path(__file__).resolve().parents[1]


def setup_case(tmp_path,kind='source_summary'):
    key=hashlib.sha256(b'SYNTHETIC_REVIEW_TEST_KEY_ONLY').digest()
    keyfile=tmp_path/'review.key';keyfile.write_bytes(key);keyfile.chmod(0o600)
    store=SQLiteRegistry(tmp_path/'kb',review_key_file=keyfile)
    entry=Knowledge(knowledge_id='SYNTHETIC_REVIEW_ONLY',category='KB-S',title='模拟条目非教材',content='模拟建议，只供测试，不是花滑动作知识',lesson_ids=['L05'],version=1,source_id='SYNTHETIC_SOURCE',source_title='模拟来源',source_locator='模拟PDF1页',content_kind=kind)
    store.save(entry)
    files=[];reports=[]
    for number,(kind,basis) in enumerate([('source_report','original_source_excerpt'),('specialist_report','specialist_review')]):
        file=tmp_path/f'synthetic-{number}.txt';file.write_text('SYNTHETIC evidence only '+str(number));files.append(file)
        report=EvidenceReport(evidence_id=f'SYNTHETIC_E{number}',knowledge_id=entry.knowledge_id,knowledge_version=1,knowledge_digest=knowledge_digest(entry.model_dump()),kind=kind,basis_kind=basis,artifact_name=file.name,artifact_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),source_id=entry.source_id,locator=entry.source_locator,statement='模拟核对意见，不是真实审核',reviewer='SYNTHETIC_REVIEWER_ONLY',review_date=None)
        store.save_report(report);reports.append(report)
    record=ReviewDecision(review_id='SYNTHETIC_R1',knowledge_id=entry.knowledge_id,knowledge_version=1,knowledge_digest=knowledge_digest(entry.model_dump()),source_evidence_id=reports[0].evidence_id,specialist_evidence_id=reports[1].evidence_id,decision='approved_for_lesson_draft',approved_statement=entry.content,lesson_ids=['L05'],reviewer='SYNTHETIC_REVIEWER_ONLY',review_date=None)
    return store,entry,record,key,keyfile,files,reports


def request():
    return LessonRequest(lesson_id='L05',conditions=dict(student_count=10,skill_level='初级',coach_count=1,teacher_count=1,usable_area_m2=100.,declared_practice_capacity=10,equipment_sets=10,safe_waiting_area=True,venue_conditions='模拟场地',equipment_conditions='模拟装备'))


def approve(store,record,key,files):
    return store.apply_decision(seal(record.model_dump(),key),source_artifact=files[0],specialist_artifact=files[1])


def test_signed_review_bound_to_sources_restarts_and_cites(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    assert store.teaching_evidence('L05')==[]
    approve(store,record,key,files)
    plan=build_framework(request(),store)
    item=plan['technical_guidance'][0]
    assert item['knowledge_id']==entry.knowledge_id and item['source_id']==entry.source_id
    assert item['source_locator']==entry.source_locator and item['statement']==entry.content
    assert item['identity_assurance']=='local_operator_attestation_only'
    assert plan['requires_teacher_review'] and plan['review_status']=='pending_review'
    assert sum(x['minutes'] for x in plan['teaching_flow']['phases'])==45
    assert plan['organization']['status']=='withheld' # missing teacher prerequisite confirmation
    store.close()
    store=SQLiteRegistry(tmp_path/'kb',review_key_file=keyfile)
    assert store.teaching_evidence('L05')[0]['review_id']==record.review_id
    assert store.teaching_evidence('L04')==[]
    assert len(store.evidence_reports())==2
    store.close()
    disabled=SQLiteRegistry(tmp_path/'kb');assert disabled.teaching_evidence('L05')==[];disabled.close()


def test_forgery_missing_original_and_revocation(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    with pytest.raises(RegistryError):store.apply_decision(seal(record.model_dump(),b'x'*32),source_artifact=files[0],specialist_artifact=files[1])
    with pytest.raises(RegistryError):store.apply_decision(seal(record.model_dump(),key))
    assert store.teaching_evidence('L05')==[]
    approve(store,record,key,files)
    revoke=ReviewDecision(**{**record.model_dump(),'review_id':'SYNTHETIC_REVOKE','decision':'revoked'})
    store.apply_decision(seal(revoke.model_dump(),key))
    assert store.teaching_evidence('L05')==[]
    store.close()


@pytest.mark.parametrize('mutation',[
 {'knowledge_digest':'0'*64},{'approved_statement':'篡改的模拟建议'},{'lesson_ids':['L04']},
 {'reviewer':'DIFFERENT_SYNTHETIC_REVIEWER'},
])
def test_binding_changes_rejected(tmp_path,mutation):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    changed=ReviewDecision(**{**record.model_dump(),**mutation})
    with pytest.raises(RegistryError):approve(store,changed,key,files)
    assert store.teaching_evidence('L05')==[];store.close()


def test_summary_or_directory_does_not_become_verified(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path,'catalogue_lead')
    with pytest.raises(RegistryError):approve(store,record,key,files)
    store.close()


def test_new_version_cannot_reuse_old_approval(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    approve(store,record,key,files)
    store.save(Knowledge(**{**entry.model_dump(),'version':2,'content':'模拟修订'}))
    assert store.teaching_evidence('L05')==[];store.close()


def test_unsigned_reports_and_web_cannot_approve(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    origin='http://127.0.0.1:8767';headers={'Origin':origin,'X-CoachLoop-Console':'1'}
    with TestClient(create_console_app(knowledge_store=store),base_url=origin,client=('127.0.0.1',55200)) as client:
        assert client.get('/api/v3/evidence').status_code==401
        client.get('/')
        assert client.post('/api/v3/import',json={'entries':[entry.model_dump()],'reviews':[record.model_dump()]},headers=headers).status_code==422
        assert client.post('/api/v3/evidence',json={**reports[0].model_dump(),'system_trusted':True},headers=headers).status_code==422
        assert client.post('/api/v3/reviews/apply',json=seal(record.model_dump(),key).model_dump(),headers=headers).status_code==404
        plan=client.post('/api/v3/plans/draft',json=request().model_dump(),headers=headers).json()
        assert plan['technical_guidance']==[] and len(plan['evidence_reports'])==2
        assert all(e['review_date'] is None for e in plan['evidence_reports'])


def test_supplied_import_package_is_pending_and_provenance_retained():
    data=json.loads((ROOT/'docs/p32-input/p32-knowledge-import.json').read_text())
    archive=Archive.model_validate(data)
    assert len(archive.entries)==23
    assert {e.category for e in archive.entries}=={'KB-S','KB-P','KB-E'}
    assert all(e.source_verification_status==e.specialist_review_status=='pending' for e in archive.entries)
    assert all(e.candidate_version=='draft-0.1' and e.version==1 for e in archive.entries)
    item=next(e for e in archive.entries if e.knowledge_id=='K011')
    assert item.source_locator=='PDF94–104；印刷80–90' and item.content_kind=='course_proposal'
    reports=json.loads((ROOT/'docs/p32-input/p32-evidence-reports.json').read_text())['reports']
    assert len(reports)==46 and all(r['reviewer'] is None and r['review_date'] is None for r in reports)
    assert all(EvidenceReport.model_validate(r).basis_kind in ('supplied_summary','user_statement') for r in reports)


def test_schema_migration_preserves_p31_history(tmp_path):
    directory=tmp_path/'kb';directory.mkdir(mode=0o700);database=directory/'knowledge.sqlite3'
    connection=sqlite3.connect(database)
    connection.execute('CREATE TABLE revisions(knowledge_id TEXT,version INTEGER,payload TEXT,PRIMARY KEY(knowledge_id,version))')
    old=dict(knowledge_id='SYNTHETIC_OLD',category='KB-E',title='模拟旧数据',content='模拟内容',lesson_ids=['L05'],source_id='',source_title='',source_locator='',source_verification_status='pending',specialist_review_status='pending',version=1)
    connection.execute('INSERT INTO revisions VALUES(?,?,?)',(old['knowledge_id'],1,json.dumps(old)))
    connection.execute('PRAGMA user_version=1');connection.commit();connection.close();database.chmod(0o600)
    store=SQLiteRegistry(directory)
    assert store.history(old['knowledge_id'])[0]['content']==old['content']
    assert store._connection.execute('PRAGMA user_version').fetchone()[0]==2
    assert store.evidence_reports()==[];store.close()


def test_wrong_artifact_hash_blocks_review(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    files[0].write_text('SYNTHETIC changed artifact')
    with pytest.raises(RegistryError):approve(store,record,key,files)
    assert store.teaching_evidence('L05')==[];store.close()


def test_batch_reports_atomic_and_report_claim_cannot_replace_original(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    first=EvidenceReport(**{**reports[0].model_dump(),'evidence_id':'SYNTHETIC_NEW1'})
    bad=EvidenceReport(**{**reports[0].model_dump(),'evidence_id':'SYNTHETIC_NEW2','knowledge_digest':'0'*64})
    with pytest.raises(RegistryError):store.save_reports([first,bad])
    assert len(store.evidence_reports())==2
    summary=EvidenceReport(**{**reports[0].model_dump(),'evidence_id':'SYNTHETIC_SUMMARY','basis_kind':'supplied_summary'})
    store.save_report(summary)
    claimed=ReviewDecision(**{**record.model_dump(),'source_evidence_id':summary.evidence_id})
    with pytest.raises(RegistryError):approve(store,claimed,key,files)
    assert store.teaching_evidence('L05')==[];store.close()


def test_withdrawn_guidance_not_reexported_from_saved_plan(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    approve(store,record,key,files)
    origin='http://127.0.0.1:8767';headers={'Origin':origin,'X-CoachLoop-Console':'1'}
    with TestClient(create_console_app(knowledge_store=store),base_url=origin,client=('127.0.0.1',55200)) as client:
        client.get('/')
        plan=client.post('/api/v3/plans/draft',json=request().model_dump(),headers=headers).json()
        assert plan['technical_guidance']
        revoked=ReviewDecision(**{**record.model_dump(),'review_id':'SYNTHETIC_WITHDRAWAL','decision':'revoked'})
        store.apply_decision(seal(revoked.model_dump(),key))
        exported=client.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).json()
        assert exported['technical_guidance']==exported['formal_teaching_evidence']==[]
        assert exported['withdrawn_evidence'][0]['knowledge_id']==entry.knowledge_id
        assert exported['knowledge_inventory'][0]['system_review_status']=='withdrawn_or_stale'
        history=client.get('/api/v3/plans/history',params={'plan_id':plan['plan_id']}).json()
        assert history['versions'][0]['technical_guidance']==[]
