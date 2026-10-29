"""Offline checks do not claim PostgreSQL/RLS acceptance."""
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.postgresql import dialect
from storage.teaching.models import Base
from storage.teaching.mock_data import mock_plan_payload


def test_models_are_isolated_and_postgresql_specific():
    assert len(Base.metadata.tables)==6
    assert all(t.schema=='teaching' for t in Base.metadata.tables.values())
    for table in Base.metadata.tables.values():
        ddl=str(CreateTable(table).compile(dialect=dialect()))
        assert "data_domain = 'mock'" in ddl
        assert 'tenant_id' in ddl


def test_fixture_is_explicitly_synthetic():
    payload=mock_plan_payload()
    assert payload['schema_version']=='db-a-1'
    assert payload['safety_precautions']['safety_review_status']=='unreviewed'
    assert payload['load_accounting']['group_active_minutes']==33.75


def test_migration_rejects_non_mock_database_before_connect(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    import pytest
    monkeypatch.setenv('TEACHING_DATABASE_URL','postgresql+psycopg://127.0.0.1/production')
    monkeypatch.setenv('TEACHING_ALLOW_MIGRATION','mock-only')
    with pytest.raises(RuntimeError,match='mock-only opt-in'):
        command.upgrade(Config(str(Path(__file__).resolve().parents[2]/'teaching_alembic.ini')),'head')
