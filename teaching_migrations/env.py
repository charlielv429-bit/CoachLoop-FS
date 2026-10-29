"""Explicit mock/test DB only. Never reads the legacy PGDATABASE_URL."""
import os
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from storage.teaching.models import Base

url = make_url(os.environ["TEACHING_DATABASE_URL"])
if (url.get_backend_name() != "postgresql" or
        os.environ.get("TEACHING_ALLOW_MIGRATION") != "mock-only" or
        not url.database or not url.database.endswith(("_test", "_mock"))):
    raise RuntimeError("DB-A migration requires explicit mock-only opt-in and a PostgreSQL *_test/*_mock database")
if context.is_offline_mode():
    raise RuntimeError("DB-A uses PostgreSQL transactional DDL; run against an isolated mock database")
with create_engine(url, hide_parameters=True).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata,
                      version_table="teaching_alembic_version", include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()
