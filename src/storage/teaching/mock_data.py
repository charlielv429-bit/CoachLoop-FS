"""Entirely synthetic DB-A fixture; no videos, student identities or legacy imports."""
import json
from uuid import uuid4
from sqlalchemy import insert, text
from .models import Class, Lesson, TrainingSession, PoseEvent


def mock_plan_payload():
    return {
        "schema_version": "db-a-1",
        "guiding_ideology": {"content": "Synthetic teaching example"},
        "teaching_material_analysis": {"content": "Synthetic beginner template"},
        "learner_analysis": {"content": "Synthetic participants only"},
        "venue_equipment": {"organization_status": "pending_confirmation"},
        "safety_precautions": {"safety_review_status": "unreviewed"},
        "teaching_flow": {"total_minutes": 45, "prep_minutes": 9, "main_minutes": 29, "closing_minutes": 7},
        "load_accounting": {"total_minutes": 45, "group_active_minutes": 33.75,
                            "individual_active_minutes": 22.5, "avg_hr": 140, "kind": "estimated"},
    }


def seed_mock_chain(teacher, agent, coach, tenant_id):
    """Uses separately authenticated engines, never the legacy database factory.

    Mock teacher approval is a workflow demo, not approval of real teaching safety.
    """
    code = uuid4().hex
    with teacher.begin() as conn:
        class_id = conn.execute(insert(Class).values(tenant_id=tenant_id,
            class_code="MOCK-"+code[:12], display_name="Synthetic class", student_count=20).returning(Class.id)).scalar_one()
        lesson_id = conn.execute(insert(Lesson).values(tenant_id=tenant_id, class_id=class_id,
            lesson_code="MOCK-"+code[:12]).returning(Lesson.id)).scalar_one()
    with agent.begin() as conn:
        plan_id = conn.execute(text("SELECT teaching.create_draft(:lesson,CAST(:payload AS jsonb))"),
            {"lesson": lesson_id, "payload": json.dumps(mock_plan_payload())}).scalar_one()
        conn.execute(text("SELECT teaching.review_plan(:id,'pending',0,'Synthetic submission')"), {"id": plan_id})
    with teacher.begin() as conn:
        conn.execute(text("SELECT teaching.review_plan(:id,'approved',1,'Synthetic teacher workflow only')"), {"id": plan_id})
        session_id = conn.execute(insert(TrainingSession).values(tenant_id=tenant_id,lesson_id=lesson_id,
            lesson_plan_id=plan_id,session_code="MOCK-"+code[:12],participant_code="MOCK-P001",
            video_object_key="mock://videos/"+code,features_object_key="mock://features/"+code).returning(TrainingSession.id)).scalar_one()
        event_id = conn.execute(insert(PoseEvent).values(tenant_id=tenant_id,training_session_id=session_id,
            analysis_run_id=uuid4(),legacy_event_id="evt_"+code[:12],feature="knee_angle_deg",
            frame_start=10,frame_end=20,start_time_ms=100,end_time_ms=200,deviation_max=12,
            original_event={"feature":"knee_angle_deg","frame_start":10,"frame_end":20,
                            "start_time_ms":100,"end_time_ms":200,"deviation_max":12},
            source_snapshot={"is_mock":True,"source":"mock://synthetic"}).returning(PoseEvent.id)).scalar_one()
    with coach.begin() as conn:
        review_id = conn.execute(text("SELECT teaching.review_event(:id,'confirmed',0,:key,'Synthetic observable change only')"),
            {"id":event_id,"key":uuid4()}).scalar_one()
    return dict(class_id=class_id,lesson_id=lesson_id,plan_id=plan_id,session_id=session_id,event_id=event_id,review_id=review_id)
