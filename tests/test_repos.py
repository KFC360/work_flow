from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.services.app_config import (
    MailConfig,
    read_app_config,
    write_app_config,
)
from app.services.config_agent import write_agent
from app.services.git_repo import inspect_origin, parse_origin_full_name
from app.services.github_api import GitHubAPIError
from tests.conftest_git import init_bare_and_clone


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
    monkeypatch.setattr("app.services.app_config.get_settings", lambda: type("S", (), {"config_yaml_path": cfg})())
    csrf = _login(client, db)
    resp = client.post("/settings", data={"csrf_token": csrf, "agent": "claude"}, follow_redirects=False)
    assert resp.status_code == 303
    text = cfg.read_text(encoding="utf-8")
    assert "agent: claude" in text
    assert "mail:" in text


def _patch_config_path(monkeypatch, cfg: Path) -> None:
    monkeypatch.setattr(
        "app.services.app_config.get_settings",
        lambda: type("S", (), {"config_yaml_path": cfg})(),
    )


def _mail(**overrides: object) -> MailConfig:
    values: dict[str, object] = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "security": "starttls",
        "username": "notify",
        "from_address": "notify@example.com",
        "from_name": "GitHub 工作流",
        "default_to": "ops@example.com",
    }
    values.update(overrides)
    return MailConfig(**values)


def test_app_config_missing_file_defaults(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    _patch_config_path(monkeypatch, cfg)

    config = read_app_config()
    assert config.agent is None
    assert config.mail.enabled is False
    assert config.mail.smtp_port == 0
    assert config.mail.security == ""
    assert config.warning is None


def test_app_config_write_atomic_and_preserves_unknown_keys(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("agent: opencode\nunknown_key: keep-me\n", encoding="utf-8")
    _patch_config_path(monkeypatch, cfg)

    write_app_config("claude", _mail())

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["agent"] == "claude"
    assert data["unknown_key"] == "keep-me"
    assert data["mail"] == {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "security": "starttls",
        "username": "notify",
        "from_address": "notify@example.com",
        "from_name": "GitHub 工作流",
        "default_to": "ops@example.com",
    }
    assert "password" not in cfg.read_text(encoding="utf-8").lower()
    assert not (tmp_path / "config.yaml.tmp").exists()


def test_app_config_write_failure_cleans_tmp(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    _patch_config_path(monkeypatch, cfg)

    def fail_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.services.app_config.os.replace", fail_replace)
    with pytest.raises(OSError):
        write_app_config("claude", _mail())
    assert not (tmp_path / "config.yaml.tmp").exists()


def test_app_config_bad_values_are_not_silently_coerced(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "agent: nope\nmail:\n  enabled: 'yes'\n  smtp_port: abc\n  security: tls\n",
        encoding="utf-8",
    )
    _patch_config_path(monkeypatch, cfg)

    config = read_app_config()
    assert config.agent is None
    assert config.mail.enabled is False
    assert config.mail.smtp_port == 0
    assert config.mail.security == ""


def test_app_config_malformed_yaml_reports_warning(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("agent: [\n", encoding="utf-8")
    _patch_config_path(monkeypatch, cfg)

    config = read_app_config()
    assert config.agent is None
    assert config.mail.enabled is False
    assert config.warning

    write_app_config("claude", _mail())
    rebuilt = read_app_config()
    assert rebuilt.agent == "claude"
    assert rebuilt.mail.smtp_host == "smtp.example.com"



def _seed_repo(db: Session, *, gh_id: int = 10, full_name: str = "acme/demo", **overrides):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=gh_id,
        account_type="Organization",
        login="acme",
        name="Acme Inc",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    data = {
        "company_id": company.id,
        "github_repo_id": gh_id,
        "name": "demo",
        "github_full_name": full_name,
        "description": "示例仓库",
        "html_url": "https://github.com/acme/demo",
        "default_branch": "main",
        "private": False,
    }
    data.update(overrides)
    repo = repository_crud.upsert_from_github(db, **data)
    return company, repo


def _seed_issue(db: Session, repo, *, number: int, kind: str, status: str, state: str = "open"):
    issue, _ = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=9000 + number,
        number=number,
        title=f"issue-{number}",
        body="b",
        html_url=f"https://github.com/acme/demo/issues/{number}",
        author_login="dev",
        github_state=state,
        label_names=[],
        github_updated_at=None,
        action="opened",
    )
    issue.kind = kind
    issue.status = status
    db.commit()
    db.refresh(issue)
    return issue


def _git_repo(tmp_path: Path, *, origin_url: str = "https://github.com/acme/demo.git", foundation: bool = True) -> Path:
    _bare, clone = init_bare_and_clone(tmp_path)
    if foundation:
        docs = clone / "docs"
        docs.mkdir()
        (docs / "README.md").write_text("# foundation\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/README.md"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "docs"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "set-url", "origin", origin_url],
        cwd=clone,
        check=True,
        capture_output=True,
    )
    return clone


def test_inspect_origin_states(tmp_path: Path) -> None:
    assert inspect_origin(None, "acme/demo").state == "none"
    assert inspect_origin(tmp_path / "missing", "acme/demo").state == "unavailable"

    clone = _git_repo(tmp_path / "match")
    assert inspect_origin(clone, "acme/demo").state == "match"
    assert inspect_origin(clone, "acme/other").state == "mismatch"

    local_origin = _git_repo(tmp_path / "local", origin_url=str(tmp_path / "bare.git"))
    info = inspect_origin(local_origin, "acme/demo")
    assert info.state == "mismatch"
    assert "无法解析" in info.detail or "不是可解析" in info.detail


def test_repo_page_shows_identity_metrics_and_summary(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_repo(
        db,
        language="Python",
        stargazers_count=1234,
        forks_count=56,
        open_issues_count=7,
        topics=["fastapi", "ops"],
        license_spdx="MIT",
        license_name="MIT License",
        pushed_at=datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc),
        homepage="https://example.com",
        visibility="public",
    )
    _seed_issue(db, repo, number=1, kind="feature", status="recorded")
    _seed_issue(db, repo, number=2, kind="feature", status="pr_opened")
    _seed_issue(db, repo, number=3, kind="feature", status="failed")
    _seed_issue(db, repo, number=4, kind="support", status="support_open")
    _seed_issue(db, repo, number=5, kind="feature", status="recorded", state="closed")

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    text = resp.text
    assert "所属公司" in text
    assert f"/companies/{repo.company_id}" in text
    assert "Acme Inc" in text
    assert "@acme" in text
    assert "GitHub 仓库 ID" in text
    assert f">{repo.github_repo_id}<" in text
    assert "完整名称" in text
    assert "收录于" in text
    assert "Python" in text
    assert "1,234" in text
    assert ">56<" in text
    assert "GitHub 开放 Issue" in text
    assert "MIT" in text
    assert "fastapi" in text
    assert "ops" in text
    assert "https://example.com" in text
    assert "https://github.com/acme/demo/issues" in text
    assert "包含 Pull Request" in text

    assert "本系统" in text
    assert "未结束功能迭代" in text
    assert "人工介入待处理" in text
    assert "三类可重叠" in text
    feature_block = text[text.index("未结束功能迭代") : text.index("未结束功能迭代") + 400]
    support_block = text[text.index("人工介入待处理") : text.index("人工介入待处理") + 400]
    assert ">2<" in feature_block
    assert ">1<" in support_block
    assert f"/repos/{repo.id}/issues?kind=feature&amp;status=unfinished&amp;github_state=open" in text
    assert f"/repos/{repo.id}/issues?kind=support&amp;status=support_open&amp;github_state=open" in text
    assert f"/repos/{repo.id}/issues?status=failed&amp;github_state=open" in text


def test_repo_page_empty_values_and_unsafe_homepage(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_repo(db, description=None, homepage="javascript:alert(1)", visibility=None)

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    text = resp.text
    assert "无描述" in text
    assert "—" in text
    assert ">None<" not in text
    assert ">null<" not in text
    assert 'href="javascript:' not in text
    assert "javascript:alert(1)" in text


def test_repo_page_archived_and_disabled_warning(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_repo(db, archived=True, disabled=True)

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert "已归档" in resp.text
    assert "已禁用" in resp.text
    assert "该仓库已在 GitHub 归档并禁用" in resp.text
    assert "本页不改变任务按钮条件" in resp.text


def test_repo_page_origin_match_and_foundation_exists(client: TestClient, db: Session, tmp_path: Path) -> None:
    _login(client, db)
    clone = _git_repo(tmp_path)
    _company, repo = _seed_repo(db)
    repo.local_path = str(clone)
    repo.doc_dir = "docs"
    db.commit()

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert "匹配" in resp.text
    assert "存在" in resp.text
    assert "docs/README.md" in resp.text
    assert "origin/main" in resp.text


def test_repo_page_origin_mismatch_still_checks_foundation(
    client: TestClient, db: Session, tmp_path: Path
) -> None:
    _login(client, db)
    clone = _git_repo(tmp_path, origin_url="https://github.com/other/repo.git")
    _company, repo = _seed_repo(db)
    repo.local_path = str(clone)
    repo.doc_dir = "docs"
    db.commit()

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    text = resp.text
    assert "origin 与 GitHub 仓库名不一致" in text
    assert "不一致" in text
    assert "https://github.com/other/repo.git" in text
    assert "存在" in text
    assert "结果仅供参考" in text


def test_repo_page_origin_unavailable(client: TestClient, db: Session, tmp_path: Path) -> None:
    _login(client, db)
    _company, repo = _seed_repo(db)
    repo.local_path = str(tmp_path / "missing")
    repo.doc_dir = "docs"
    db.commit()

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert "无法校验" in resp.text
    assert "无法检查（路径不可用）" in resp.text


def test_repo_page_without_local_path(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_repo(db)
    _seed_issue(db, repo, number=1, kind="feature", status="recorded")

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert "未填写路径，无法检查" in resp.text
    assert "未结束功能迭代" in resp.text


def test_repo_page_get_does_not_instantiate_github_client(
    client: TestClient, db: Session, monkeypatch
) -> None:
    _login(client, db)
    _company, repo = _seed_repo(db)
    calls: list[str] = []

    def _fail(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("GitHubClient must not be constructed on repo GET")

    monkeypatch.setattr("app.api.v1.repos.GitHubClient", _fail)
    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert calls == []


def test_resync_failure_only_updates_sync_error(client: TestClient, db: Session, tmp_path: Path, monkeypatch) -> None:
    csrf = _login(client, db)
    _company, repo = _seed_repo(
        db,
        stargazers_count=1234,
        topics=["keep"],
        language="Python",
    )
    repo.local_path = str(tmp_path)
    repo.doc_dir = "docs"
    db.commit()

    class FailingClient:
        def get_repository(self, repo_id: int):
            raise GitHubAPIError("network down", status_code=500)

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.api.v1.repos.GitHubClient", lambda: FailingClient())
    resp = client.post(
        f"/repos/{repo.id}/resync",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert f"/companies/{repo.company_id}" in resp.headers["location"]
    db.refresh(repo)
    assert repo.sync_error == "network down"
    assert repo.local_path == str(tmp_path)
    assert repo.doc_dir == "docs"
    assert repo.stargazers_count == 1234
    assert repo.topics == ["keep"]
    assert repo.language == "Python"
