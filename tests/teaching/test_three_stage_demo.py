"""Three-stage synthetic chain on real restricted PostgreSQL roles only."""
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, insert, text

from agents.postlesson_agent import draft_from_database
from integrations.prelesson.api import create_app as prelesson_app
from integrations.prelesson.schemas import DraftResponse
from integrations.reviewed_training.api import create_app as training_app
from integrations.reviewed_training.json_codec import encode
from integrations.reviewed_training.schemas import ImportRequest
from integrations.reviewed_training.service import TrustedIdentity
from integrations.three_stage_demo import prelesson, database_plan_payload, synthetic_video_stages, import_payload
from storage.teaching.models import Class, Lesson, TrainingSession


@pytest.fixture
def demo_roles(database):
    admin = database[0]
    tenant = uuid4()
    engines = {}
    for role in ('agent', 'teacher', 'coach', 'reader', 'importer'):
        login = f'tdb_{tenant.hex}_{role}'
        password = secrets.token_urlsafe(24)
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'CREATE ROLE "{login}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD \'{password}\'')
                connection.exec_driver_sql(f'GRANT teaching_{role} TO "{login}"')
        except Exception:
            pytest.fail('Disposable demo login provisioning failed; details omitted', pytrace=False)
        engines[role] = create_engine(admin.url.set(username=login, password=password), hide_parameters=True)
    yield tenant, engines
    for engine in engines.values():
        engine.dispose()


def test_postlesson_rejects_forged_identity_and_unavailable_session(demo_roles):
    from fastapi import HTTPException
    tenant, roles = demo_roles
    forged = TrustedIdentity(uuid4(), f'tdb_{tenant.hex}_reader', roles['reader'])
    with pytest.raises(HTTPException) as error:
        draft_from_database(forged, uuid4(), uuid4())
    assert error.value.status_code == 403
    bound = TrustedIdentity(tenant, f'tdb_{tenant.hex}_reader', roles['reader'])
    with pytest.raises(HTTPException) as error:
        draft_from_database(bound, uuid4(), uuid4())
    assert error.value.status_code == 404


@pytest.mark.parametrize('status', ['pending', 'confirmed', 'normal_movement', 'tracking_error', 'uncertain'])
def test_complete_mock_chain_keeps_review_boundaries(database, demo_roles, status):
    tenant, roles = demo_roles
    token = secrets.token_urlsafe(32)
    request = dict(class_label='MOCK-THREE-STAGE-01', student_count=20, theme='冰上双足滑行与身体姿态控制',
        skill_level='零基础', total_minutes=45, coach_count=1, teacher_count=1,
        venue_conditions='合成冰场，容量与组织待教师现场确认', equipment_conditions='合成冰鞋护具20套')
    with TestClient(prelesson_app(token)) as client:
        response = client.post('/api/v1/lesson-plans/draft', json=request, headers={'Authorization': 'Bearer ' + token})
        assert response.status_code == 200
        plan = DraftResponse.model_validate(response.json())
    with roles['teacher'].begin() as connection:
        class_id = connection.scalar(insert(Class).values(tenant_id=tenant, class_code='MOCK-DEMO',
            display_name='Synthetic class only', student_count=20).returning(Class.id))
        lesson_id = connection.scalar(insert(Lesson).values(tenant_id=tenant, class_id=class_id,
            lesson_code='MOCK-DEMO').returning(Lesson.id))
    with roles['agent'].begin() as connection:
        plan_id = connection.scalar(text('SELECT teaching.create_draft(:lesson,CAST(:payload AS jsonb))'),
            dict(lesson=lesson_id, payload=encode(database_plan_payload(plan))))
        connection.execute(text("SELECT teaching.review_plan(:id,'pending',0,'MOCK submission only')"), dict(id=plan_id))
    with roles['teacher'].begin() as connection:
        # This is an explicit MOCK test actor, not a real teacher approval.
        connection.execute(text("SELECT teaching.review_plan(:id,'approved',1,'MOCK scripted role demonstration only')"), dict(id=plan_id))
        session_id = connection.scalar(insert(TrainingSession).values(tenant_id=tenant, lesson_id=lesson_id,
            lesson_plan_id=plan_id, session_code='MOCK-DEMO', participant_code='MOCK-P001',
            video_object_key='mock://videos/three-stage-no-video', features_object_key='mock://features/three-stage-keypoints').returning(TrainingSession.id))
    features, candidates, reviews = synthetic_video_stages()
    payload = import_payload(dict(class_id=class_id, lesson_id=lesson_id, session_id=session_id), reviews)
    normalized = ImportRequest.model_validate(payload)
    with database[0].begin() as connection:
        connection.execute(text('INSERT INTO teaching_ingest.mock_artifacts(id,tenant_id,payload) VALUES(:id,:tenant,CAST(:payload AS jsonb))'),
            dict(id=normalized.source.artifact_id, tenant=tenant, payload=encode(normalized.model_dump(mode='python'))))
    importer = TrustedIdentity(tenant, f'tdb_{tenant.hex}_importer', roles['importer'])
    reader = TrustedIdentity(tenant, f'tdb_{tenant.hex}_reader', roles['reader'])
    run_id = normalized.analysis_run_id
    with TestClient(training_app(lambda _: importer)) as client:
        key = str(uuid4())
        headers = {'Content-Type': 'application/json', 'Idempotency-Key': key}
        first = client.post('/api/v1/reviewed-training-results/import', content=encode(payload), headers=headers)
        assert first.status_code == 200
        replay = client.post('/api/v1/reviewed-training-results/import', content=encode(payload), headers=headers)
        assert replay.status_code == 200 and replay.json()['replayed']
        assert first.json()['receipt_id'] == replay.json()['receipt_id']
    before_review = draft_from_database(reader, session_id, run_id)
    assert before_review.observations == ()
    with roles['coach'].begin() as connection:
        for event in first.json()['events']:
            connection.execute(text('SELECT teaching.review_event(:id,:status,0,:key,:note)'),
                dict(id=event['event_id'], status=status, key=uuid4(), note='MOCK scripted state-machine demonstration, not real human review'))
    feedback = draft_from_database(reader, session_id, run_id)
    assert bool(feedback.observations) == (status in ('confirmed', 'normal_movement'))
    assert feedback.technical_error_assessment == 'not_assessed'
    assert feedback.review_status == 'draft' and feedback.requires_teacher_review
    with TestClient(training_app(lambda _: reader)) as client:
        queried = client.get(f'/api/v1/training-sessions/{session_id}/reviewed-training-results', params={'analysis_run_id': str(run_id)})
        assert queried.status_code == 200
        assert queried.json()['summary']['event_count'] == len(candidates.events)
    # Optional synthetic evidence export, controlled only by local test runner.
    destination = os.environ.get('COACHLOOP_DEMO_EVIDENCE_DIR')
    if destination and status == 'confirmed':
        evidence = dict(kind='synthetic_local_three_stage_evidence', data_domain='mock',
            transport='local_TestClient_and_isolated_PostgreSQL16_not_Coze', human_review_performed=False,
            production_modified=False, prelesson=plan.model_dump(mode='json'),
            geometry_frame_count=len(features.frames), candidate_event_count=len(candidates.events),
            import_receipt_id=first.json()['receipt_id'], replay_receipt_id=replay.json()['receipt_id'],
            database_results=queried.json(), postlesson=feedback.model_dump(mode='json'),
            feedback_teacher_review='pending_not_approved', feedback_archive='not_implemented',
            archived_training_events=True)
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'three-stage.postgresql.mock-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
