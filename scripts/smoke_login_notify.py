#!/usr/bin/env python3
"""Post-deploy smoke: Playwright login + email result via app.services.mail.

Run on the deploy host (after docker_deploy), with project .env loaded:

  uv sync --extra smoke
  uv run playwright install chromium
  uv run --extra smoke python scripts/smoke_login_notify.py

Env:
  APP_ADMIN_USER / APP_ADMIN_PASSWORD — production admin
  SMOKE_NOTIFY_TO — comma/semicolon/whitespace-separated recipients (optional)
  SMOKE_BASE_URL — default https://api.kfc360.xyz
  SMTP_PASSWORD + config.yaml mail — same path as settings test mail
"""

from __future__ import annotations

import html as html_lib
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.services.mail import MailError, send_mail  # noqa: E402

DEFAULT_BASE_URL = "https://api.kfc360.xyz"
SPLIT_RE = re.compile(r"[,;\s]+")


@dataclass
class SmokeResult:
    ok: bool
    base_url: str
    login_url: str
    final_url: str
    elapsed_ms: int
    error: str
    screenshot: Path | None
    git_sha: str


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _parse_recipients(raw: str) -> list[str]:
    if not raw.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in SPLIT_RE.split(raw.strip()):
        addr = part.strip()
        if not addr or "@" not in addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            or "unknown"
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _run_login(base_url: str, username: str, password: str) -> SmokeResult:
    from urllib.parse import urlparse

    from playwright.sync_api import sync_playwright

    login_url = f"{base_url.rstrip('/')}/login"
    started = datetime.now(timezone.utc)
    screenshot_dir = ROOT / "logs" / "smoke"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    shot: Path | None = None
    final_url = login_url
    error = ""
    ok = False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(30_000)
            page.goto(login_url, wait_until="domcontentloaded")
            page.fill("#username", username)
            page.fill("#password", password)
            page.click('button[type="submit"][data-gw-submit], button[type="submit"]')
            # Success: 303 to /; failure: 200 re-render /login — wait for either.
            try:
                page.wait_for_url(
                    lambda url: "/login" not in urlparse(url).path.rstrip("/"),
                    timeout=20_000,
                )
            except Exception:
                page.wait_for_load_state("domcontentloaded")
            final_url = page.url
            path = urlparse(final_url).path.rstrip("/") or "/"
            still_login = path == "/login" or path.endswith("/login")
            has_password = page.locator("#password").count() > 0
            if still_login or has_password:
                err_el = page.locator(".alert-error, #login-error")
                if err_el.count():
                    error = (err_el.first.inner_text() or "").strip() or "仍停留在登录页"
                else:
                    error = "登录后仍停留在登录页或登录表单仍可见"
                shot = screenshot_dir / f"fail-{started.strftime('%Y%m%dT%H%M%SZ')}.png"
                page.screenshot(path=str(shot), full_page=True)
            else:
                ok = True
            browser.close()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return SmokeResult(
        ok=ok,
        base_url=base_url,
        login_url=login_url,
        final_url=final_url,
        elapsed_ms=elapsed_ms,
        error=error,
        screenshot=shot,
        git_sha=_git_sha(),
    )


def _notify(result: SmokeResult, recipients: list[str]) -> None:
    if not recipients:
        print("smoke: SMOKE_NOTIFY_TO empty — skip mail", flush=True)
        return
    status = "OK" if result.ok else "FAIL"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[deploy smoke {status}] {result.git_sha} · {now}"
    err_html = (
        f"<p><strong>错误</strong>：{html_lib.escape(result.error)}</p>"
        if result.error
        else ""
    )
    shot_html = (
        f"<p>失败截图已写到服务器：<code>{html_lib.escape(str(result.screenshot))}</code></p>"
        if result.screenshot
        else ""
    )
    html_body = f"""
    <h2>部署后登录冒烟 · {html_lib.escape(status)}</h2>
    <ul>
      <li>提交：<code>{html_lib.escape(result.git_sha)}</code></li>
      <li>时间：{html_lib.escape(now)}</li>
      <li>耗时：{result.elapsed_ms} ms</li>
      <li>登录页：{html_lib.escape(result.login_url)}</li>
      <li>最终 URL：{html_lib.escape(result.final_url)}</li>
    </ul>
    {err_html}
    {shot_html}
    <p>此邮件表示部署后对生产登录页的自动探测结果，不是业务 Issue 通知。</p>
    """
    text = (
        f"smoke {status} sha={result.git_sha} elapsed={result.elapsed_ms}ms\n"
        f"login={result.login_url}\nfinal={result.final_url}\n"
        f"error={result.error or '-'}\n"
    )
    send_mail(recipients, subject, html_body, text_fallback=text)
    print(f"smoke: mail sent to {len(recipients)} recipient(s)", flush=True)


def main() -> int:
    user = _env("APP_ADMIN_USER")
    password = _env("APP_ADMIN_PASSWORD")
    base_url = _env("SMOKE_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    recipients = _parse_recipients(_env("SMOKE_NOTIFY_TO"))

    if not user or not password:
        print("smoke: missing APP_ADMIN_USER or APP_ADMIN_PASSWORD", file=sys.stderr)
        result = SmokeResult(
            ok=False,
            base_url=base_url,
            login_url=f"{base_url.rstrip('/')}/login",
            final_url="",
            elapsed_ms=0,
            error="缺少 APP_ADMIN_USER 或 APP_ADMIN_PASSWORD",
            screenshot=None,
            git_sha=_git_sha(),
        )
        try:
            _notify(result, recipients)
        except MailError as exc:
            print(f"smoke: mail failed: {exc}", file=sys.stderr)
        return 1

    print(f"smoke: login {base_url.rstrip('/')}/login as {user!r}", flush=True)
    result = _run_login(base_url, user, password)
    print(
        f"smoke: {'OK' if result.ok else 'FAIL'} final={result.final_url} "
        f"elapsed={result.elapsed_ms}ms error={result.error or '-'}",
        flush=True,
    )
    try:
        _notify(result, recipients)
    except MailError as exc:
        print(f"smoke: mail failed: {exc}", file=sys.stderr)
        # Login success + mail failure: still fail CD so ops notice missing mail.
        return 1 if result.ok else 1
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
