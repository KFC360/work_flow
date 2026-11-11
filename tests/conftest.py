from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

# Ensure env before app imports settings cache
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://github_workflow:github_workflow@127.0.0.1:55438/github_workflow",
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
    eng = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool, pool_pre_ping=True)
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
