"""Unverified import receipts, pinned synthetic manifests and controlled importer role."""
from pathlib import Path
from alembic import op
revision='0003_training_import'
down_revision='0002_event_snapshot'
branch_labels=None
depends_on=None


def upgrade():
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(
        Path(__file__).with_name('0003_training_import.sql').read_text())


def downgrade():
    op.execute('DROP FUNCTION teaching_ingest.import_results(uuid,jsonb)')
    op.execute('DROP SCHEMA teaching_ingest CASCADE')
    op.execute("""CREATE OR REPLACE FUNCTION teaching.current_tenant() RETURNS uuid LANGUAGE sql STABLE
        SET search_path=pg_catalog AS $$ SELECT ((regexp_match(session_user::text,
        '^tdb_([0-9a-f]{32})_(agent|teacher|coach|reader)$'))[1])::uuid $$""")
    # NOLOGIN importer role is retained as cluster-level security provisioning.
