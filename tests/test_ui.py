from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.crud import webhook_delivery as delivery_crud


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def _seed_company_repo(db: Session, *, account_type: str = "User"):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=101,
        account_type=account_type,
        login="acme",
        name="Acme",
        description="示例公司",
        avatar_url=None,
        html_url="https://github.com/acme",
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=1010,
        name="demo",
        github_full_name="acme/demo",
        description="示例仓库",
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )
    return company, repo


def _seed_issue(db: Session, repo, *, number: int, status: str, kind: str, title: str):
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=5000 + number,
        number=number,
        title=title,
        body="正文第一行\n正文第二行",
        html_url=f"https://github.com/acme/demo/issues/{number}",
        author_login="dev",
        github_state="open",
        label_names=[],
        github_updated_at=datetime(2026, 11, 10, 8, 30, tzinfo=timezone.utc),
        action="opened",
    )
    issue.status = status
    issue.kind = kind
    issue.iteration_no = 1
    issue.design_doc_path = "docs/v0001-1/design.md"
    issue.design_doc_text = "# design"
    db.commit()
    db.refresh(issue)
    return issue


def test_console_pages_render(client: TestClient, db: Session, tmp_path: Path, monkeypatch) -> None:
    csrf = _login(client, db)
    company, repo = _seed_company_repo(db)
    repo.local_path = str(tmp_path)
    db.commit()
    issue = _seed_issue(db, repo, number=1, status="recorded", kind="feature", title="首个功能")
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    job.status = "succeeded"
    job.finished_at = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    job.log_excerpt = "job-log-line"
    db.commit()
    monkeypatch.setattr("app.services.actions.read_agent", lambda: "claude")

    resp = client.get("/")
    assert resp.status_code == 200
    assert "个人账号" in resp.text
    assert "Acme" in resp.text
    assert "总览" in resp.text
    assert 'aria-current="page"' in resp.text

    resp = client.get(f"/companies/{company.id}")
    assert resp.status_code == 200
    assert "acme/demo" in resp.text
    assert "重新同步" in resp.text
    assert "共" in resp.text

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    assert "GitHub 资料" in resp.text
    assert "本地配置" in resp.text
    assert "服务器项目路径" in resp.text
    assert 'aria-describedby="local_path-help"' in resp.text

    resp = client.get(f"/repos/{repo.id}/issues")
    assert resp.status_code == 200
    assert "应用筛选" in resp.text
    assert "首个功能" in resp.text
    assert "编写文档" in resp.text
    assert "data-gw-confirm" in resp.text
    assert 'data-confirm-title="编写设计文档"' in resp.text
    assert f'name="csrf_token" value="{csrf}"' in resp.text

    resp = client.get(f"/issues/{issue.id}")
    assert resp.status_code == 200
    assert "任务与 Worker" in resp.text
    assert 'id="issue-live-status"' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'id="issue-log"' in resp.text
    assert "job-log-line" in resp.text
    assert "job #" in resp.text
    assert "onsubmit=\"return confirm" not in resp.text
    assert resp.text.index("流程操作") < resp.text.index("Issue 摘要") < resp.text.index("最新任务日志")

    resp = client.get("/deliveries")
    assert resp.status_code == 200
    assert "还没有投递" in resp.text

    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "全站代理" in resp.text
    assert "Worker 心跳" in resp.text

    resp = client.get("/companies/999999")
    assert resp.status_code == 404
    assert "页面未找到" in resp.text

    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 303


def test_empty_and_filtered_states(client: TestClient, db: Session) -> None:
    _login(client, db)
    company, repo = _seed_company_repo(db)
    _seed_issue(db, repo, number=2, status="recorded", kind="feature", title="只有功能迭代")

    resp = client.get(f"/repos/{repo.id}/issues?kind=feature&github_state=closed")
    assert "没有符合筛选的 Issue" in resp.text
    assert "清除筛选" in resp.text

    resp = client.get(f"/repos/{repo.id}/issues?kind=support")
    assert "还没有人工介入 Issue" in resp.text
    assert "只收录" in resp.text

    resp = client.get(f"/companies/{company.id}?page=2")
    assert resp.status_code == 200
    assert "该公司下还没有仓库" in resp.text


def test_confirm_modal_and_delivery_retry(client: TestClient, db: Session, tmp_path: Path, monkeypatch) -> None:
    _login(client, db)
    company, repo = _seed_company_repo(db)
    repo.local_path = str(tmp_path)
    db.commit()
    issue = _seed_issue(db, repo, number=3, status="pending_codegen", kind="feature", title="待生成")
    monkeypatch.setattr("app.services.actions.read_agent", lambda: "claude")

    resp = client.get(f"/issues/{issue.id}")
    assert 'id="gw-confirm"' in resp.text
    assert 'data-gw-confirm' in resp.text
    assert "确认执行" in resp.text
    assert "重新编写文档" in resp.text

    ok = delivery_crud.create_queued(
        db,
        delivery_id="abcdef1234567890",
        event="issues",
        action="opened",
        repository_id=repo.github_repo_id,
        payload={},
    )
    assert ok is not None
    delivery_crud.mark_succeeded(db, ok)
    failed = delivery_crud.create_queued(
        db,
        delivery_id="ffff1234567890",
        event="issues",
        action="closed",
        repository_id=repo.github_repo_id,
        payload={},
    )
    assert failed is not None
    delivery_crud.mark_failed(db, failed, error="token 401 " + "x" * 200)

    resp = client.get("/deliveries")
    assert resp.status_code == 200
    assert "acme/demo" in resp.text
    assert "重试投递" in resp.text
    assert resp.text.count("重试投递") == 1
    assert "成功" in resp.text
    assert 'title="token 401' in resp.text

    resp = client.get("/deliveries?status=failed")
    assert "没有符合筛选的投递" not in resp.text
    assert "重试投递" in resp.text


def test_status_fragment_polling_contract(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_company_repo(db)
    issue = _seed_issue(db, repo, number=4, status="drafting", kind="feature", title="轮询")

    resp = client.get(f"/issues/{issue.id}/status-fragment")
    assert resp.status_code == 200
    assert 'data-done="0"' in resp.text
    assert 'id="issue-live-status"' in resp.text
    assert 'id="issue-log-live"' in resp.text

    issue.status = "recorded"
    db.commit()
    resp = client.get(f"/issues/{issue.id}/status-fragment")
    assert resp.status_code == 200
    assert 'data-done="1"' in resp.text

    resp = client.get("/issues/1/status-fragment", follow_redirects=False)
    assert resp.status_code in {200, 404}


_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _RegionIds(HTMLParser):
    """Collect HTML ids that appear inside a data-gw-region marker."""

    def __init__(self, region: str):
        super().__init__(convert_charrefs=True)
        self.region = region
        self.depth = 0
        self.region_depth: int | None = None
        self.ids: list[str] = []

    def _record(self, attrs) -> None:
        attrs = dict(attrs)
        if attrs.get("data-gw-region") == self.region:
            self.region_depth = self.depth
        if self.region_depth is not None and attrs.get("id"):
            self.ids.append(attrs["id"])

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _VOID_TAGS:
            self._record(attrs)
            return
        self.depth += 1
        self._record(attrs)

    def handle_startendtag(self, tag, attrs) -> None:
        self._record(attrs)

    def handle_endtag(self, tag) -> None:
        if tag in _VOID_TAGS:
            return
        if self.region_depth is not None and self.depth == self.region_depth:
            self.region_depth = None
        self.depth = max(self.depth - 1, 0)


def _region_ids(html: str, region: str) -> list[str]:
    parser = _RegionIds(region)
    parser.feed(html)
    return parser.ids


def test_issue_detail_two_column_layout_and_markdown(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_company_repo(db)
    issue = _seed_issue(db, repo, number=7, status="recorded", kind="feature", title="双栏与正文")
    issue.body = (
        "# 正文标题\n\n"
        "第一段有 **粗体**、*斜体*、`行内代码` 和 [安全链接](https://example.com)。\n\n"
        "- 列表一\n- 列表二\n\n"
        "```python\nprint('<code>')\n```\n\n"
        "| 列 | 值 |\n| --- | --- |\n| A | 1 |"
    )
    issue.design_doc_text = "# 设计源文"
    db.commit()

    resp = client.get(f"/issues/{issue.id}")
    assert resp.status_code == 200
    text = resp.text

    assert 'data-gw-region="issue-side"' in text
    ids = _region_ids(text, "issue-side")
    assert "task-title" in ids
    assert "log-title" in ids
    assert "issue-live-status" in ids
    assert "issue-log" in ids
    assert "issue-log-jump" in ids
    assert ids.index("task-title") < ids.index("log-title")
    assert text.count('id="issue-log"') == 1

    assert '<div class="gw-markdown">' in text
    assert "<h3>正文标题</h3>" in text
    assert "<strong>粗体</strong>" in text
    assert "<em>斜体</em>" in text
    assert "<code>行内代码</code>" in text
    assert '<a href="https://example.com" rel="noopener noreferrer">安全链接</a>' in text
    assert "<table>" in text and "<td>1</td>" in text
    assert 'tabindex="0"><code>print(\'&lt;code&gt;\')' in text
    assert "&lt;h3&gt;" not in text

    body_card = text.split('id="issue-body-title"', 1)[1].split("</section>", 1)[0]
    assert "<h1" not in body_card
    assert "<h2" not in body_card

    design_start = text.index('id="design-doc-title"')
    assert "<pre" in text[design_start:]
    assert "># 设计源文</pre>" in text


def test_issue_detail_markdown_xss_and_empty_body(client: TestClient, db: Session) -> None:
    _login(client, db)
    _company, repo = _seed_company_repo(db)
    issue = _seed_issue(db, repo, number=8, status="recorded", kind="feature", title="安全正文")
    issue.body = (
        "<p>安全段落</p>"
        "<script>alert('xss-body')</script>"
        '<img src=x onerror="alert(1)">'
        '<a href="javascript:alert(1)">坏链接</a>'
        '<iframe src="https://evil.example"></iframe>'
    )
    db.commit()

    resp = client.get(f"/issues/{issue.id}")
    text = resp.text
    assert "安全段落" in text
    assert "xss-body" not in text
    assert "onerror" not in text
    assert "javascript:" not in text
    assert "evil.example" not in text

    issue.body = "   "
    db.commit()
    resp = client.get(f"/issues/{issue.id}")
    assert "该 Issue 没有正文。" in resp.text


def test_issue_list_url_preserves_filters() -> None:
    from app.api.v1.issues import _issue_list_url

    assert (
        _issue_list_url(
            7, kind="feature", status="recorded", github_state="open", page=2
        )
        == "/repos/7/issues?kind=feature&status=recorded&github_state=open&page=2"
    )
    assert (
        _issue_list_url(7, kind=None, status=None, github_state="", page=1)
        == "/repos/7/issues"
    )
    assert (
        _issue_list_url(
            7, kind="feature", status="unfinished", github_state="open", page=2
        )
        == "/repos/7/issues?kind=feature&status=unfinished&github_state=open&page=2"
    )


def test_repo_card_sections_and_summary_links(client: TestClient, db: Session) -> None:
    _login(client, db)
    company, repo = _seed_company_repo(db)
    _seed_issue(db, repo, number=1, status="recorded", kind="feature", title="待处理功能")

    resp = client.get(f"/repos/{repo.id}")
    assert resp.status_code == 200
    text = resp.text
    assert "GitHub 资料" in text
    assert "所属公司" in text
    assert f"/companies/{company.id}" in text
    assert "GitHub 仓库 ID" in text
    assert "本系统" in text
    assert "未结束功能迭代" in text
    assert "人工介入待处理" in text
    assert "三类可重叠" in text
    assert f'href="/repos/{repo.id}/issues?kind=feature&amp;status=unfinished&amp;github_state=open"' in text
    assert f'href="/repos/{repo.id}/issues?kind=support&amp;status=support_open&amp;github_state=open"' in text
    assert f'href="/repos/{repo.id}/issues?status=failed&amp;github_state=open"' in text


def test_login_page_markup(client: TestClient, db: Session) -> None:
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "显示" in resp.text
    assert 'aria-label="显示口令"' in resp.text
    assert "从 Issue 到 Pull Request" in resp.text

    user_crud.ensure_admin_user(db)
    resp = client.post("/login", data={"username": "admin", "password": "bad"})
    assert resp.status_code == 200
    assert 'aria-invalid="true"' in resp.text
    assert "autofocus" in resp.text
    assert 'value="admin"' in resp.text
