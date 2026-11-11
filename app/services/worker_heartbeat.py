from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.settings import PROJECT_ROOT

HEARTBEAT_PATH = PROJECT_ROOT / "logs" / "worker-heartbeat.json"
HEARTBEAT_STALE_SEC = 30
IDLE_HEARTBEAT_INTERVAL_SEC = 5
PROGRESS_HEARTBEAT_INTERVAL_SEC = 3


@dataclass(frozen=True)
class HeartbeatView:
    status: str  # idle | running | stale | missing
    updated_at: str | None
    job_id: int | None
    issue_id: int | None
    action: str | None
    pid: int | None
    age_sec: float | None
    label: str


def write_heartbeat(
    *,
    job_id: int | None = None,
    issue_id: int | None = None,
    action: str | None = None,
    path: Path | None = None,
) -> None:
    target = path or HEARTBEAT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "issue_id": issue_id,
        "action": action,
        "pid": os.getpid(),
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(target.parent),
        delete=False,
    ) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, target)


def read_heartbeat(
    *,
    path: Path | None = None,
    stale_sec: int = HEARTBEAT_STALE_SEC,
    now: float | None = None,
) -> HeartbeatView:
    target = path or HEARTBEAT_PATH
    if not target.is_file():
        return HeartbeatView(
            status="missing",
            updated_at=None,
            job_id=None,
            issue_id=None,
            action=None,
            pid=None,
            age_sec=None,
            label="无心跳",
        )
    try:
        payload: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return HeartbeatView(
            status="stale",
            updated_at=None,
            job_id=None,
            issue_id=None,
            action=None,
            pid=None,
            age_sec=None,
            label="无心跳",
        )
    updated_raw = payload.get("updated_at")
    age: float | None = None
    if isinstance(updated_raw, str):
        try:
            dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (now if now is not None else time.time()) - dt.timestamp()
        except ValueError:
            age = None
    job_id = payload.get("job_id")
    issue_id = payload.get("issue_id")
    action = payload.get("action")
    pid = payload.get("pid")
    if age is None or age > stale_sec:
        return HeartbeatView(
            status="stale",
            updated_at=updated_raw if isinstance(updated_raw, str) else None,
            job_id=job_id if isinstance(job_id, int) else None,
            issue_id=issue_id if isinstance(issue_id, int) else None,
            action=action if isinstance(action, str) else None,
            pid=pid if isinstance(pid, int) else None,
            age_sec=age,
            label="无心跳",
        )
    if job_id is None:
        return HeartbeatView(
            status="idle",
            updated_at=updated_raw if isinstance(updated_raw, str) else None,
            job_id=None,
            issue_id=None,
            action=None,
            pid=pid if isinstance(pid, int) else None,
            age_sec=age,
            label="Worker 空闲",
        )
    return HeartbeatView(
        status="running",
        updated_at=updated_raw if isinstance(updated_raw, str) else None,
        job_id=job_id if isinstance(job_id, int) else None,
        issue_id=issue_id if isinstance(issue_id, int) else None,
        action=action if isinstance(action, str) else None,
        pid=pid if isinstance(pid, int) else None,
        age_sec=age,
        label=f"执行中 job #{job_id}" + (f" / issue #{issue_id}" if issue_id else ""),
    )
