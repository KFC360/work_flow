from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import company as company_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.services.config_agent import write_agent
from app.services.git_repo import parse_origin_full_name


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def test_parse_origin() -> None:
    assert parse_origin_full_name("git@github.com:acme/demo.git") == "acme/demo"
    assert parse_origin_full_name("https://github.com/acme/demo.git") == "acme/demo"


def test_company_list_empty(client: TestClient, db: Session) -> None:
    _login(client, db)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "还没有收到 GitHub Issue 通知" in resp.text or "还没有公司" in resp.text


def test_save_doc_dir_rejects_absolute(client: TestClient, db: Session, tmp_path: Path) -> None:
    _login(client, db)
    csrf = _login(client, db)
    company = company_crud.upsert_from_github(
        db,
        github_account_id=1,
        account_type="Organization",
        login="acme",
        name="Acme",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=10,
        name="demo",
        github_full_name="acme/demo",
        description=None,
        html_url=None,
        default_branch="main",
        private=False,
    )
    resp = client.post(
        f"/repos/{repo.id}",
        data={"csrf_token": csrf, "local_path": "", "doc_dir": "/etc"},
    )
    assert resp.status_code == 200
    assert "相对路径" in resp.text


def test_settings_write_agent(client: TestClient, db: Session, tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-for-pytest-xx")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    object.__setattr__(settings, "config_yaml_path", cfg) if False else None
    # frozen dataclass — patch via monkeypatch on get_settings return
    monkeypatch.setattr("app.services.config_agent.get_settings", lambda: type("S", (), {"config_yaml_path": cfg})())
    csrf = _login(client, db)
    resp = client.post("/settings", data={"csrf_token": csrf, "agent": "claude"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "agent: claude" in cfg.read_text(encoding="utf-8")
