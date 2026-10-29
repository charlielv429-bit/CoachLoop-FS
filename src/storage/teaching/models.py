"""DB-A schema. Use the independent Alembic migration, never create_all at startup."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (CheckConstraint, Computed, DateTime, ForeignKeyConstraint,
                        Index, Integer, MetaData, Numeric, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="teaching")


class Record:
    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    data_domain: Mapped[str] = mapped_column(String(8), nullable=False, server_default="mock")
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, server_default="mock_import")
    source_ref: Mapped[str | None] = mapped_column(Text)
    source_schema_version: Mapped[str] = mapped_column(String(16), nullable=False, server_default="db-a-1")
    created_by: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("session_user"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()"))


def scope():
    return (UniqueConstraint("tenant_id", "data_domain", "id"),
            CheckConstraint("data_domain = 'mock'", name="ck_mock_only"),
            CheckConstraint("source_kind IN ('manual','agent','mock_import','v4_import','v5_import')", name="ck_source"))


def fk(column, parent):
    return ForeignKeyConstraint(["tenant_id", "data_domain", column],
                                [f"teaching.{parent}.{c}" for c in ("tenant_id", "data_domain", "id")],
                                ondelete="RESTRICT")


class Class(Record, Base):
    __tablename__ = "classes"
    class_code: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    student_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    __table_args__ = (*scope(), UniqueConstraint("tenant_id", "data_domain", "class_code"),
                      CheckConstraint("student_count > 0", name="ck_count"),
                      CheckConstraint("status IN ('draft','active','archived')", name="ck_status"))


class Lesson(Record, Base):
    __tablename__ = "lessons"
    class_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    lesson_code: Mapped[str] = mapped_column(String(32), nullable=False)
    theme_code: Mapped[str] = mapped_column(String(64), nullable=False, server_default="beginner_two_foot_glide_posture")
    skill_level: Mapped[str] = mapped_column(String(16), nullable=False, server_default="beginner")
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="45")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    __table_args__ = (*scope(), fk("class_id", "classes"),
                      UniqueConstraint("tenant_id", "data_domain", "class_id", "lesson_code"),
                      CheckConstraint("total_minutes = 45", name="ck_time"),
                      CheckConstraint("theme_code = 'beginner_two_foot_glide_posture' AND skill_level = 'beginner'", name="ck_template"),
                      CheckConstraint("status IN ('draft','scheduled','completed','cancelled')", name="ck_status"))


class LessonPlan(Record, Base):
    __tablename__ = "lesson_plans"
    lesson_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="45")
    prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    main_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    closing_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    load_total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    group_active_minutes: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    individual_active_minutes: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    avg_hr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    measurement_kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="estimated")
    group_density: Mapped[Decimal] = mapped_column(Numeric, Computed("group_active_minutes / total_minutes * 100"))
    individual_density: Mapped[Decimal] = mapped_column(Numeric, Computed("individual_active_minutes / total_minutes * 100"))
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_history: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    __table_args__ = (*scope(), fk("lesson_id", "lessons"),
        UniqueConstraint("tenant_id", "data_domain", "lesson_id", "version_no"),
        UniqueConstraint("tenant_id", "data_domain", "lesson_id", "id", name="uq_plan_lesson"),
        CheckConstraint("version_no > 0", name="ck_version"),
        CheckConstraint("total_minutes = 45 AND load_total_minutes = total_minutes AND prep_minutes BETWEEN 8 AND 10 AND main_minutes BETWEEN 28 AND 30 AND closing_minutes BETWEEN 5 AND 7 AND prep_minutes + main_minutes + closing_minutes = total_minutes", name="ck_time"),
        CheckConstraint("group_active_minutes BETWEEN 0 AND total_minutes AND individual_active_minutes BETWEEN 0 AND total_minutes AND avg_hr BETWEEN 20 AND 250", name="ck_load"),
        CheckConstraint("measurement_kind IN ('estimated','measured')", name="ck_kind"),
        CheckConstraint("review_status IN ('draft','pending','approved','needs_revision')", name="ck_review"),
        CheckConstraint("jsonb_typeof(review_history) = 'array'", name="ck_history"),
        CheckConstraint("(review_status IN ('approved','needs_revision') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL) OR (review_status IN ('draft','pending') AND reviewed_by IS NULL AND reviewed_at IS NULL)", name="ck_reviewer"),
        CheckConstraint("teaching.valid_plan_payload(payload, prep_minutes, main_minutes, closing_minutes, group_active_minutes, individual_active_minutes, avg_hr, measurement_kind)", name="ck_payload"),
        Index("ix_plans_review", "tenant_id", "data_domain", "review_status"))


class TrainingSession(Record, Base):
    __tablename__ = "training_sessions"
    lesson_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    lesson_plan_id: Mapped[UUID | None] = mapped_column(PGUUID)
    session_code: Mapped[str] = mapped_column(String(40), nullable=False)
    participant_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="planned")
    video_object_key: Mapped[str | None] = mapped_column(Text)
    features_object_key: Mapped[str | None] = mapped_column(Text)
    analysis_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (*scope(), fk("lesson_id", "lessons"),
        ForeignKeyConstraint(["tenant_id", "data_domain", "lesson_id", "lesson_plan_id"],
                             [f"teaching.lesson_plans.{c}" for c in ("tenant_id", "data_domain", "lesson_id", "id")], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "data_domain", "session_code"),
        CheckConstraint("status IN ('planned','completed','cancelled')", name="ck_status"),
        CheckConstraint("participant_code ~ '^MOCK-[A-Z0-9_-]+$'", name="ck_anonymous"),
        CheckConstraint("(video_object_key IS NULL OR video_object_key LIKE 'mock://videos/%') AND (features_object_key IS NULL OR features_object_key LIKE 'mock://features/%')", name="ck_mock_assets"),
        Index("ix_sessions_lesson", "tenant_id", "data_domain", "lesson_id"))


class PoseEvent(Record, Base):
    __tablename__ = "pose_events"
    training_session_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    legacy_event_id: Mapped[str | None] = mapped_column(String(16))
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    frame_start: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_end: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    end_time_ms: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    deviation_max: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    original_event: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="candidate")
    __table_args__ = (*scope(), fk("training_session_id", "training_sessions"),
        UniqueConstraint("tenant_id", "data_domain", "training_session_id", "analysis_run_id", "feature", "frame_start", "frame_end"),
        UniqueConstraint("tenant_id", "data_domain", "training_session_id", "analysis_run_id", "legacy_event_id"),
        CheckConstraint("legacy_event_id IS NULL OR legacy_event_id ~ '^evt_[0-9a-f]{12}$'", name="ck_legacy_id"),
        CheckConstraint("feature IN ('knee_angle_deg','torso_pitch_deg','hip_ankle_offset_norm')", name="ck_feature"),
        CheckConstraint("frame_start >= 0 AND frame_end >= frame_start AND start_time_ms >= 0 AND end_time_ms >= start_time_ms AND end_time_ms < 'Infinity'::numeric AND deviation_max >= 0 AND deviation_max < 'Infinity'::numeric", name="ck_geometry"),
        CheckConstraint("quality_status IN ('candidate','quarantined')", name="ck_quality"),
        CheckConstraint("jsonb_typeof(original_event) = 'object' AND jsonb_typeof(source_snapshot) = 'object'", name="ck_snapshots"),
        CheckConstraint("COALESCE(source_snapshot->'is_mock' = 'true'::jsonb AND source_snapshot->>'source' LIKE 'mock://%', false)", name="ck_mock_snapshot"),
        CheckConstraint("COALESCE(original_event->>'feature' = feature AND (original_event->>'frame_start')::int = frame_start AND (original_event->>'frame_end')::int = frame_end, false)", name="ck_event_snapshot"),
        Index("ix_events_time", "tenant_id", "data_domain", "training_session_id", "frame_start"))


class CoachReview(Record, Base):
    __tablename__ = "coach_reviews"
    pose_event_id: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    review_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    idempotency_key: Mapped[UUID] = mapped_column(PGUUID, nullable=False)
    __table_args__ = (*scope(), fk("pose_event_id", "pose_events"),
        UniqueConstraint("tenant_id", "data_domain", "pose_event_id", "review_seq"),
        UniqueConstraint("tenant_id", "data_domain", "idempotency_key"),
        CheckConstraint("review_seq > 0", name="ck_sequence"),
        CheckConstraint("status IN ('pending','confirmed','normal_movement','tracking_error','uncertain')", name="ck_status"),
        CheckConstraint("length(note) <= 1000 AND length(reviewer_id) > 0", name="ck_note"))
