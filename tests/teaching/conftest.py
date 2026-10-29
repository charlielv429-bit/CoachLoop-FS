"""PostgreSQL integration tests explicitly opt in to a disposable loopback database."""
import os
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from storage.teaching.mock_data import seed_mock_chain

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database():
    raw = os.environ.get("TEACHING_DATABASE_URL")
    if not raw:
        pytest.skip("PostgreSQL DB-A tests need explicit TEACHING_DATABASE_URL; SQLite is not acceptance")
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql" or url.host not in ("127.0.0.1","localhost")
            or url.port != 55432 or url.database != "coachloop_db_a_test"
            or os.environ.get("TEACHING_ALLOW_MIGRATION") != "mock-only"):
        pytest.fail("Refusing integration tests outside disposable DB-A loopback instance")
    admin = create_engine(url, hide_parameters=True)
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT current_database()")) == "coachloop_db_a_test"
        assert int(conn.scalar(text("SHOW server_version_num"))) >= 150000
    config = Config(str(ROOT / "teaching_alembic.ini"))
    command.upgrade(config,"head")
    command.downgrade(config,"base")
    command.upgrade(config,"head")
    actors = {}
    for tenant in (uuid4(),uuid4()):
        actors[tenant] = {}
        for role in ("agent","teacher","coach","reader"):
            login = f"tdb_{tenant.hex}_{role}"
            password = secrets.token_urlsafe(24)
            # Identifiers derive solely from generated UUIDs and fixed suffixes.
            # Hide all provisioning errors to avoid exposing generated test passwords.
            try:
                with admin.begin() as conn:
                    conn.exec_driver_sql(f'CREATE ROLE "{login}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD \'{password}\'')
                    conn.exec_driver_sql(f'GRANT teaching_{role} TO "{login}"')
            except Exception:
                pytest.fail("Disposable test login provisioning failed", pytrace=False)
            actors[tenant][role] = create_engine(url.set(username=login,password=password),hide_parameters=True)
    yield admin, actors
    for engines in actors.values():
        for engine in engines.values(): engine.dispose()
    admin.dispose()


@pytest.fixture
def actors(database):
    return database[1]


@pytest.fixture
def tenant(actors):
    return next(iter(actors))


@pytest.fixture
def chain(actors,tenant):
    engines=actors[tenant]
    return seed_mock_chain(engines['teacher'],engines['agent'],engines['coach'],tenant)
