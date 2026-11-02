"""Complete backup restore with SYNTHETIC review authority; no real approvals."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from test_p32_reviews import setup_case, approve
from integrations.curriculum_v3.full_backup import FullBackup, canonical, snapshot
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.registry import Archive, Knowledge, RegistryError, source_conflict
from integrations.curriculum_v3.review import EvidenceReport, ReviewDecision, seal
from integrations.prelesson.console import create_console_app

ROOT=Path(__file__).resolve().parents[1]


def history_case(tmp_path):
    store,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    approve(store,record,key,files)
    # Lexically before approval ID; sorting IDs would incorrectly undo revocation.
    revoke=ReviewDecision(**{**record.model_dump(),'review_id':'AAA_SYNTHETIC_REVOKE','decision':'revoked'})
    store.apply_decision(seal(revoke.model_dump(),key))
    return store,entry,key,keyfile


def test_complete_review_and_revocation_roundtrip_retains_original_order(tmp_path):
    source,entry,key,keyfile=history_case(tmp_path)
    before=source.export_full()
    assert [d['record']['decision'] for d in before['review_decisions']]==['approved_for_lesson_draft','revoked']
    target=SQLiteRegistry(tmp_path/'restored',review_key_file=keyfile)
    assert target.restore_full(FullBackup.model_validate(before))=={'knowledge_versions':1,'evidence_reports':2,'review_decisions':2}
    assert target.export_full()==before
    assert target.teaching_evidence('L05')==[]
    target.close()
    target=SQLiteRegistry(tmp_path/'restored',review_key_file=keyfile)
    assert target.export_full()==before and target.teaching_evidence('L05')==[]
    target.close();source.close()


def test_approved_snapshot_restores_only_with_correct_key(tmp_path):
    source,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    approve(source,record,key,files);backup=source.export_full()
    target=SQLiteRegistry(tmp_path/'restored',review_key_file=keyfile)
    target.restore_full(FullBackup.model_validate(backup))
    assert target.teaching_evidence('L05')==source.teaching_evidence('L05')
    target.close()
    disabled=SQLiteRegistry(tmp_path/'restored');assert disabled.teaching_evidence('L05')==[]
    with pytest.raises(RegistryError):disabled.export_full()
    disabled.close();source.close()


@pytest.mark.parametrize('change',['drop_revocation','reorder','strip_authentication','change_decision'])
def test_tampered_history_cannot_reactivate_approval(tmp_path,change):
    source,entry,key,keyfile=history_case(tmp_path)
    bad=source.export_full()
    if change=='drop_revocation':bad['review_decisions'].pop()
    elif change=='reorder':bad['review_decisions'].reverse()
    elif change=='strip_authentication':bad['authentication_tag']=None
    else:bad['review_decisions'][-1]['record']['decision']='approved_for_lesson_draft'
    # Recomputing a public checksum is insufficient to authenticate the history.
    body={k:v for k,v in bad.items() if k not in ('snapshot_digest','authentication_tag')}
    bad['snapshot_digest']=hashlib.sha256(canonical(body)).hexdigest()
    target=SQLiteRegistry(tmp_path/'target',review_key_file=keyfile)
    with pytest.raises(RegistryError):target.restore_full(FullBackup.model_validate(bad))
    assert target.export()['entries']==[] and target.evidence_reports()==[]
    assert target._connection.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]==0
    source.close();target.close()


def test_missing_wrong_key_and_occupied_target_never_overwrite(tmp_path):
    source,entry,key,keyfile=history_case(tmp_path);backup=FullBackup.model_validate(source.export_full())
    empty=SQLiteRegistry(tmp_path/'empty')
    with pytest.raises(RegistryError):empty.restore_full(backup)
    assert not empty.export()['entries'];empty.close()
    wrong=tmp_path/'wrong.key';wrong.write_bytes(b'x'*32);wrong.chmod(0o600)
    mismatched_source=SQLiteRegistry(tmp_path/'kb',review_key_file=wrong)
    with pytest.raises(RegistryError):mismatched_source.export_full()
    mismatched_source.close()
    empty=SQLiteRegistry(tmp_path/'wrong',review_key_file=wrong)
    with pytest.raises(RegistryError):empty.restore_full(backup)
    assert not empty.export()['entries'];empty.close()
    before=source.export_full()
    with pytest.raises(RegistryError):source.restore_full(backup)
    assert source.export_full()==before;source.close()


def test_invalid_binding_rolls_back_whole_complete_restore(tmp_path):
    source,entry,key,keyfile=history_case(tmp_path)
    body=source.export_full()
    body={k:v for k,v in body.items() if k not in ('snapshot_digest','authentication_tag')}
    body['evidence_reports'][1]['knowledge_digest']='0'*64
    signed=snapshot(body,key)
    target=SQLiteRegistry(tmp_path/'target',review_key_file=keyfile)
    with pytest.raises(RegistryError):target.restore_full(signed)
    assert not target.export()['entries'] and not target.evidence_reports()
    source.close();target.close()


def test_real_candidate_package_roundtrip_does_not_upgrade_or_rewrite(tmp_path):
    archive=Archive.model_validate(json.loads((ROOT/'docs/p32-input/p32-knowledge-import.json').read_text()))
    reports=[EvidenceReport.model_validate(r) for r in json.loads((ROOT/'docs/p32-input/p32-evidence-reports.json').read_text())['reports']]
    source=SQLiteRegistry(tmp_path/'source');source.import_archive(archive);source.save_reports(reports)
    before=source.export_full()
    target=SQLiteRegistry(tmp_path/'target');target.restore_full(FullBackup.model_validate(before))
    assert target.export_full()==before and source.export_full()==before
    assert len(target.export()['entries'])==23 and len(target.evidence_reports())==46
    assert not target.teaching_evidence('L05') and before['review_decisions']==[]
    for entry in target.search():
        assert entry['source_verification_status']==entry['specialist_review_status']=='pending'
        if entry['knowledge_id'] in ('K010','K011','K018'):
            assert entry['source_conflict_status']=='unresolved'
            assert entry['source_locator']=='PDF94–104；印刷80–90'
            assert 'PDF94起转入后压步' in entry['source_conflict_note']
        if entry['knowledge_id'] in ('K011','K018'):assert entry['content_kind']=='course_proposal'
    source.close();target.close()


def test_cli_complete_backup_restore_and_ordinary_web_rejects(tmp_path):
    source,entry,key,keyfile=history_case(tmp_path);expected=source.export_full();source.close()
    file=tmp_path/'synthetic.kb-full-backup.json'
    def run(action,directory,key_path=None):
        command=[sys.executable,'-B',str(ROOT/'scripts/manage_local_knowledge.py'),'--kb-dir',str(directory),action,'--file',str(file)]
        if key_path:command+=['--review-key-file',str(key_path)]
        return subprocess.run(command,capture_output=True,text=True,timeout=10)
    assert run('full-backup',tmp_path/'kb').returncode==1 and not file.exists()
    assert run('full-backup',tmp_path/'kb',keyfile).returncode==0
    assert file.stat().st_mode & 0o777==0o600
    assert run('full-backup',tmp_path/'kb',keyfile).returncode==1
    assert run('full-restore',tmp_path/'restored',keyfile).returncode==0
    assert run('full-restore',tmp_path/'restored',keyfile).returncode==1
    restored=SQLiteRegistry(tmp_path/'restored',review_key_file=keyfile)
    assert restored.export_full()==expected and restored.teaching_evidence('L05')==[]
    origin='http://127.0.0.1:8767';headers={'Origin':origin,'X-CoachLoop-Console':'1'}
    with TestClient(create_console_app(knowledge_store=restored),base_url=origin,client=('127.0.0.1',55210)) as client:
        client.get('/')
        assert client.post('/api/v3/import',json=expected,headers=headers).status_code==422
        assert client.post('/api/v3/full-restore',json=expected,headers=headers).status_code==404
        assert restored.export_full()==expected


def test_known_page_conflict_cannot_be_approved_even_with_machine_tag(tmp_path):
    source,entry,record,key,keyfile,files,reports=setup_case(tmp_path)
    # Synthetic text/artifacts deliberately use the affected candidate identifier
    # to exercise its read-only advisory. This is never imported into real data.
    conflict=Knowledge(**{**entry.model_dump(),'knowledge_id':'K010','source_id':'B02',
        'source_locator':'PDF94–104；印刷80–90','candidate_version':'draft-0.1'})
    source.save(conflict)
    from integrations.curriculum_v3.review import knowledge_digest
    evidence=[]
    for i,report in enumerate(reports):
        evidence.append(EvidenceReport(**{**report.model_dump(),'evidence_id':f'SYNTHETIC_CONFLICT_E{i}',
            'knowledge_id':conflict.knowledge_id,'knowledge_digest':knowledge_digest(conflict.model_dump()),
            'source_id':conflict.source_id,'locator':conflict.source_locator}))
    source.save_reports(evidence)
    decision=ReviewDecision(**{**record.model_dump(),'review_id':'SYNTHETIC_CONFLICT_R',
        'knowledge_id':conflict.knowledge_id,'knowledge_digest':knowledge_digest(conflict.model_dump()),
        'source_evidence_id':evidence[0].evidence_id,'specialist_evidence_id':evidence[1].evidence_id})
    with pytest.raises(RegistryError,match='Unresolved'):
        approve(source,decision,key,files)
    assert source._connection.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]==0
    source.close()
