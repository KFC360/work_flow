from __future__ import annotations

from app.services.agent_test_db import (
    agent_env_for_test_db,
    job_database_name,
    job_database_url,
    maintenance_url,
)


def test_job_database_naming() -> None:
    assert job_database_name(42) == "gw_job_42"
    url = job_database_url(
        "postgresql+psycopg://u:p@127.0.0.1:5432/github_workflow",
        42,
    )
    assert url.endswith("/gw_job_42")
    assert "u:p@" in url
    admin = maintenance_url("postgresql+psycopg://u:p@127.0.0.1:5432/github_workflow")
    assert admin.endswith("/postgres")


def test_agent_env_for_test_db() -> None:
    env = agent_env_for_test_db("postgresql+psycopg://u:p@127.0.0.1:5432/gw_job_7")
    assert env["DATABASE_URL"].endswith("/gw_job_7")
    assert env["TEST_DATABASE_URL"] == env["DATABASE_URL"]
    assert env["ALLOW_TEST_DROP_ALL"] == "1"
    assert env["GITHUB_WORKFLOW_AGENT"] == "1"


def test_agent_env_strips_prod_but_keeps_extra(monkeypatch) -> None:
    from app.services import agent as agent_mod

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://prod@127.0.0.1:5432/github_workflow")
    extra = agent_env_for_test_db("postgresql+psycopg://u:p@127.0.0.1:5432/gw_job_9")
    env = agent_mod._agent_env(extra)
    assert env["DATABASE_URL"].endswith("/gw_job_9")
    assert "github_workflow" not in env["DATABASE_URL"].rsplit("/", 1)[-1]
