from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import DB_SCHEMA, get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute(f"SET search_path TO {DB_SCHEMA}, public")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema(connection) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}"))
