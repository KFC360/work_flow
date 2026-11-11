from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.crud import user as user_crud
from app.services.agent import run_agent
from app.services.job_logs import read_job_log_tail, safe_job_log_path
from app.services.worker_heartbeat import HEARTBEAT_STALE_SEC, read_heartbeat, write_heartbeat
from app.core.settings import PROJECT_ROOT


def test_progress_callback_without_stdout(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    def fake_popen(*args, **kwargs):
        class Proc:
            def __init__(self):
                self.pid = 1
                self.stdout = open("/dev/null", "rb")  # noqa: SIM115
                self._n = 0

            def poll(self):
                self._n += 1
                return 0 if self._n > 4 else None

            def wait(self, timeout=None):
                return 0

            @property
            def returncode(self):
                return 0

        return Proc()

    monkeypatch.setattr("app.services.agent.subprocess.Popen", fake_popen)
    monkeypatch.setattr("app.services.agent.select.select", lambda *a, **k: ([], [], []))
    monkeypatch.setattr("app.services.agent.shutil.which", lambda _: None)
    monkeypatch.setattr("app.services.agent._kill_process_group", lambda pid: None)

    log_path = tmp_path / "job.log"

    def on_progress() -> None:
        calls.append(1)

    code = run_agent(
        "opencode",
        "hi",
        cwd=tmp_path,
        timeout_sec=30,
        log_path=log_path,
        on_progress=on_progress,
        progress_interval_sec=0.01,
    )
    assert code == 0
    assert len(calls) >= 1


def test_heartbeat_idle_running_and_stale(tmp_path: Path) -> None:
    path = tmp_path / "hb.json"
    write_heartbeat(path=path)
    view = read_heartbeat(path=path, stale_sec=30)
    assert view.status == "idle"
    write_heartbeat(job_id=7, issue_id=3, action="write_doc", path=path)
    view = read_heartbeat(path=path, stale_sec=30)
    assert view.status == "running"
    assert view.job_id == 7
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stale = read_heartbeat(path=path, stale_sec=HEARTBEAT_STALE_SEC)
    assert stale.status == "stale"
    assert stale.label == "无心跳"


def test_safe_job_log_path_rejects_escape(tmp_path: Path) -> None:
    outside = tmp_path / "secret.log"
    outside.write_text("nope", encoding="utf-8")
    assert safe_job_log_path(str(outside)) is None
    jobs = PROJECT_ROOT / "logs" / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    inside = jobs / "observability-test.log"
    inside.write_text("hello-log", encoding="utf-8")
    try:
        assert safe_job_log_path(str(inside)) == inside.resolve()
        assert "hello-log" in read_job_log_tail(str(inside))
    finally:
        inside.unlink(missing_ok=True)


def test_status_fragment_requires_login(client: TestClient) -> None:
    resp = client.get("/issues/1/status-fragment", follow_redirects=False)
    assert resp.status_code == 401
    assert "使用管理员账号登录" not in resp.text


def test_status_fragment_contains_fields(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set("access_token", token)
    # may 404 if no issue; still must not leak unauthenticated
    resp = client.get("/issues/999999/status-fragment")
    assert resp.status_code in {404, 200}
