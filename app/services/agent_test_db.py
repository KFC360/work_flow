from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

_JOB_DB_RE = re.compile(r"^gw_job_\d+$")


class AgentTestDbError(Exception):
    pass


@dataclass(frozen=True)
class AgentTestDatabase:
    name: str
    url: str
    admin_url: str


def maintenance_url(database_url: str) -> str:
    """Connect to the cluster maintenance DB to CREATE/DROP databases."""
    url = make_url(database_url)
    return url.set(database="postgres").render_as_string(hide_password=False)


def job_database_name(job_id: int) -> str:
    name = f"gw_job_{int(job_id)}"
    if not _JOB_DB_RE.match(name):
        raise AgentTestDbError(f"invalid job database name: {name}")
    return name


def job_database_url(database_url: str, job_id: int) -> str:
    name = job_database_name(job_id)
    url = make_url(database_url)
    return url.set(database=name).render_as_string(hide_password=False)


def create_job_database(database_url: str, job_id: int) -> AgentTestDatabase:
    name = job_database_name(job_id)
    admin = maintenance_url(database_url)
    url = job_database_url(database_url, job_id)
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": name},
            ).scalar()
            if exists:
                _terminate_backends(conn, name)
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        logger.info(f"created agent test database {name}")
    except Exception as exc:  # noqa: BLE001
        raise AgentTestDbError(str(exc)) from exc
    finally:
        engine.dispose()
    return AgentTestDatabase(name=name, url=url, admin_url=admin)


def drop_job_database(database_url: str, job_id: int) -> None:
    name = job_database_name(job_id)
    admin = maintenance_url(database_url)
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": name},
            ).scalar()
            if not exists:
                return
            _terminate_backends(conn, name)
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        logger.info(f"dropped agent test database {name}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"failed to drop agent test database {name}: {exc}")
    finally:
        engine.dispose()


def _terminate_backends(conn, name: str) -> None:
    conn.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :n AND pid <> pg_backend_pid()"
        ),
        {"n": name},
    )


def agent_env_for_test_db(test_url: str) -> dict[str, str]:
    return {
        "DATABASE_URL": test_url,
        "TEST_DATABASE_URL": test_url,
        "ALLOW_TEST_DROP_ALL": "1",
        "GITHUB_WORKFLOW_AGENT": "1",
    }
