"""Mock-only teaching schema and least-privilege policies.

DDL snapshots are frozen alongside this revision, not imported from live ORM metadata.
"""
from pathlib import Path
from alembic import op
revision = "0001_teaching"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for name in ("0001_prerequisites.sql", "0001_tables.sql", "0001_security.sql"):
        op.get_bind().execution_options(no_parameters=True).exec_driver_sql(Path(__file__).with_name(name).read_text())


def downgrade():
    # Explicit migration administrator only. NOLOGIN group roles are retained:
    # role membership is security provisioning, not application data.
    op.execute("DROP SCHEMA teaching CASCADE")
