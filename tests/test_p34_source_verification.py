"""Real supplied-page metadata; approvals in existing review tests remain SYNTHETIC."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from integrations.curriculum_v3.registry import Archive, Knowledge, RegistryError
from integrations.curriculum_v3.review import EvidenceBundle, knowledge_digest
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.full_backup import FullBackup
from integrations.curriculum_v3.planning import build_framework, LessonRequest, guard_current_evidence

ROOT=Path(__file__).resolve().parents[1]


def load(name):return json.loads((ROOT/name).read_text())


def packets():
    return (Archive.model_validate(load('docs/p34/knowledge-revisions.json')),
            EvidenceBundle.model_validate(load('docs/p34/source-evidence-reports.json')))


def baseline(store):
    store.import_archive(Archive.model_validate(load('docs/p32-input/p32-knowledge-import.json')))
    store.save_reports(EvidenceBundle.model_validate(load('docs/p32-input/p32-evidence-reports.json')).reports)


def request():
    return LessonRequest.model_validate(dict(lesson_id='L05',prerequisites_confirmed=False,conditions=dict(student_count=20,skill_level='初级',coach_count=2,teacher_count=1,usable_area_m2=200.,declared_practice_capacity=10,equipment_sets=20,safe_waiting_area=True,venue_conditions='合成验收条件，不是实际场地',equipment_conditions='合成验收条件，不是实际装备')))


def test_revision_schema_bindings_and_no_invented_review():
    archive,bundle=packets();manifest=load('docs/p34/artifact-manifest.json')
    entries={e.knowledge_id:e for e in archive.entries}
    assert set(entries)=={'K010','K011','K012','K018'}
    for r in bundle.reports:
        e=entries[r.knowledge_id]
        assert e.version==r.knowledge_version==2
        assert e.source_verification_status==e.specialist_review_status=='pending'
        assert r.knowledge_digest==knowledge_digest(e.model_dump())
        assert r.source_id==e.source_id and r.locator==e.source_locator
        assert r.kind=='source_report' and r.basis_kind=='original_source_excerpt'
        assert r.reviewer is r.review_date is None
        assert r.artifact_sha256==next(a['sha256'] for a in manifest['artifacts'] if a['file']==r.artifact_name)
    assert entries['K011'].content_kind==entries['K018'].content_kind=='course_proposal'
    assert '无教材逐字出处' in entries['K018'].source_locator
    assert '原PDF91／印刷77' in entries['K010'].source_locator
    assert '原PDF39／印刷29' in entries['K012'].source_locator


def test_append_restart_and_complete_backup_preserve_original_history(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');baseline(store);before=store.export_full()
    archive,bundle=packets();store.import_archive(archive);store.save_reports(bundle.reports)
    after=store.export_full();store.close()
    store=SQLiteRegistry(tmp_path/'kb')
    assert store.export_full()==after
    assert len(store.search())==23 and len(after['archive']['entries'])==27
    for original in before['archive']['entries']:
        assert original in after['archive']['entries']
    assert after['evidence_reports'][:46]==before['evidence_reports']
    assert len(after['evidence_reports'])==50 and after['review_decisions']==before['review_decisions']==[]
    assert store.teaching_evidence('L05')==[]
    for kid in ('K010','K011','K018'):
        history=store.history(kid)
        assert [e['version'] for e in history]==[1,2]
        assert history[0]['source_conflict_status']=='unresolved'
        assert history[1]['source_conflict_status']=='not_flagged' # No approval inferred.
    restored=SQLiteRegistry(tmp_path/'restored')
    restored.restore_full(FullBackup.model_validate(after))
    assert restored.export_full()==after and restored.teaching_evidence('L05')==[]
    store.close();restored.close()


def test_conflicting_revision_batch_and_evidence_are_non_destructive(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');baseline(store);archive,bundle=packets()
    bad=deepcopy(archive.model_dump());bad['entries'][-1]['version']=3
    before=store.export_full()
    with pytest.raises(RegistryError):store.import_archive(Archive.model_validate(bad))
    assert store.export_full()==before
    store.import_archive(archive);before=store.export_full()
    bad=deepcopy(bundle.model_dump());bad['reports'][-1]['knowledge_digest']='0'*64
    with pytest.raises(RegistryError):store.save_reports(EvidenceBundle.model_validate(bad).reports)
    assert store.export_full()==before
    with pytest.raises(RegistryError):store.import_archive(archive)
    assert store.export_full()==before
    store.close()


@pytest.mark.parametrize('field,value',[('source_verification_status','verified'),('specialist_review_status','approved'),('content','<script>alert(1)</script>')])
def test_revision_cannot_upgrade_or_inject(field,value):
    archive,_=packets();data=archive.entries[0].model_dump();data[field]=value
    with pytest.raises(ValidationError):Knowledge.model_validate(data)


def test_l05_uses_current_candidates_and_removes_superseded_text(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');baseline(store)
    old=build_framework(request(),store)
    archive,bundle=packets();store.import_archive(archive);store.save_reports(bundle.reports)
    stale=guard_current_evidence(old,store)
    assert stale['evidence_status']=='requires_regeneration_after_knowledge_change'
    for group in stale['l05_teaching_design']['material_groups'].values():
        for card in group:
            if card['knowledge_id'] in ('K011','K012','K018'):
                assert card['candidate_text']=='' and card['citation_status']=='superseded_or_unlinked'
    new=build_framework(request(),store)
    assert [p['minutes'] for p in new['teaching_flow']['phases']]==[9,29,7]
    assert new['technical_guidance']==new['formal_teaching_evidence']==[]
    assert new['organization']['status']=='withheld'
    design=new['l05_teaching_design']
    assert design['review_status']=='pending_review' and design['reviewed_citations']==[]
    cards=[c for g in design['material_groups'].values() for c in g]
    assert {(c['knowledge_id'],c['version']) for c in cards}=={('K011',2),('K012',2),('K018',2),('K019',1)}
    assert all(not c['is_formal_guidance'] for c in cards)
    assert all(c['source_id'] and c['source_locator'] for c in cards)
    assert all(c['system_review_status']=='pending' for c in new['knowledge_inventory'])
    store.close()
