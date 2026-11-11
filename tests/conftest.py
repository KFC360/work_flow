from __future__ import annotations

import os
from collections.abc import Generator
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

# Prefer Worker-injected ephemeral DB, then explicit TEST_DATABASE_URL, then
# local compose (55438). Never silently keep a production DATABASE_URL.
_TEST_DB_DEFAULT = (
    "postgresql+psycopg://github_workflow:github_workflow@127.0.0.1:55438/github_workflow"
)
_test_db = os.environ.get("TEST_DATABASE_URL") or _TEST_DB_DEFAULT
os.environ["DATABASE_URL"] = _test_db

if os.environ.get("GITHUB_WORKFLOW_AGENT") == "1" and not os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError(
        "Refusing to run pytest in the Worker agent without TEST_DATABASE_URL. "
        "The Worker must provision an ephemeral gw_job_* database."
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


def _is_disposable_db_url(url: str) -> bool:
    if os.environ.get("ALLOW_TEST_DROP_ALL"):
        return True
    if "55438" in url:
        return True
    path = (urlparse(url).path or "").rstrip("/")
    db_name = path.rsplit("/", 1)[-1]
    return db_name.startswith("gw_job_")


@pytest.fixture(scope="session")
def engine():
    url = os.environ["DATABASE_URL"]
    if not _is_disposable_db_url(url):
        raise RuntimeError(
            f"Refusing Base.metadata.drop_all on non-test DB URL ({url!r}). "
            "Use TEST_DATABASE_URL (compose :55438 or Worker gw_job_*), "
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
