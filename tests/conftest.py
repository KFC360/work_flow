from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

# Tests must never reuse the Worker/production DATABASE_URL. Prefer an explicit
# test URL; otherwise fall back to the local compose port only.
_TEST_DB_DEFAULT = (
    "postgresql+psycopg://github_workflow:github_workflow@127.0.0.1:55438/github_workflow"
)
_test_db = os.environ.get("TEST_DATABASE_URL") or _TEST_DB_DEFAULT
os.environ["DATABASE_URL"] = _test_db

if os.environ.get("GITHUB_WORKFLOW_AGENT") == "1":
    raise RuntimeError(
        "Refusing to run pytest inside the Worker agent environment "
        "(GITHUB_WORKFLOW_AGENT=1). This protects the production database."
    )

os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-pytest-32b!"
os.environ["APP_ADMIN_USER"] = "admin"
os.environ["APP_ADMIN_PASSWORD"] = "admin-pass"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret"

from app.core.settings import DB_SCHEMA, get_settings
from app.database.connect import Base, get_db
from app.models import User  # noqa: F401
import app.models  # noqa: F401
from main import app

get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine():
    url = os.environ["DATABASE_URL"]
    if "5432" in url and "55438" not in url and not os.environ.get("ALLOW_TEST_DROP_ALL"):
        raise RuntimeError(
            f"Refusing Base.metadata.drop_all on non-test DB URL ({url!r}). "
            "Set TEST_DATABASE_URL to the compose DB (port 55438) "
            "or set ALLOW_TEST_DROP_ALL=1 only for disposable databases."
        )
    eng = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    with eng.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}"))
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def db(engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    def _override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
