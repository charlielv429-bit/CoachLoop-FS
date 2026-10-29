"""Require all six event fields to agree with their immutable JSON snapshot.

Validation is deliberately immediate and transactional. Existing missing/conflicting
snapshots abort the upgrade; do not invent values or rewrite original evidence.
"""
from alembic import op

revision = "0002_event_snapshot"
down_revision = "0001_teaching"
branch_labels = None
depends_on = None

# Frozen migration expression: never import future live ORM metadata here.
EVENT_SNAPSHOT_CHECK = (
    "CASE WHEN jsonb_typeof(original_event->'feature') = 'string' "
    "AND jsonb_typeof(original_event->'frame_start') = 'number' "
    "AND jsonb_typeof(original_event->'frame_end') = 'number' "
    "AND jsonb_typeof(original_event->'start_time_ms') = 'number' "
    "AND jsonb_typeof(original_event->'end_time_ms') = 'number' "
    "AND jsonb_typeof(original_event->'deviation_max') = 'number' "
    "AND original_event->>'frame_start' ~ '^[0-9]+$' "
    "AND original_event->>'frame_end' ~ '^[0-9]+$' "
    "THEN COALESCE(original_event->>'feature' = feature "
    "AND (original_event->>'frame_start')::numeric = frame_start "
    "AND (original_event->>'frame_end')::numeric = frame_end "
    "AND (original_event->>'start_time_ms')::numeric = start_time_ms "
    "AND (original_event->>'end_time_ms')::numeric = end_time_ms "
    "AND (original_event->>'deviation_max')::numeric = deviation_max, false) "
    "ELSE false END"
)
OLD_CHECK = (
    "COALESCE(original_event->>'feature' = feature "
    "AND (original_event->>'frame_start')::int = frame_start "
    "AND (original_event->>'frame_end')::int = frame_end, false)"
)


def upgrade():
    op.drop_constraint("ck_event_snapshot", "pose_events", schema="teaching", type_="check")
    op.create_check_constraint("ck_event_snapshot", "pose_events", EVENT_SNAPSHOT_CHECK, schema="teaching")


def downgrade():
    op.drop_constraint("ck_event_snapshot", "pose_events", schema="teaching", type_="check")
    op.create_check_constraint("ck_event_snapshot", "pose_events", OLD_CHECK, schema="teaching")
