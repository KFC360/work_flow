from __future__ import annotations

from pathlib import Path

CONF = Path(__file__).resolve().parents[1] / "deploy" / "nginx" / "api.kfc360.xyz.conf"


def test_nginx_docs_have_basic_auth() -> None:
    text = CONF.read_text(encoding="utf-8")
    for loc in ("location /docs", "location /redoc", "location = /openapi.json"):
        assert loc in text
    assert text.count("auth_basic") >= 3
    assert "auth_basic_user_file" in text
    # webhook path should not be wrapped in auth_basic block separately —
    # it falls under location / without auth_basic
    webhook_idx = text.find("location / {")
    docs_idx = text.find("location /docs")
    assert webhook_idx != -1 and docs_idx != -1
    root_block = text[webhook_idx : webhook_idx + 400]
    assert "auth_basic" not in root_block


def test_nginx_issue_sync_has_long_read_timeout() -> None:
    text = CONF.read_text(encoding="utf-8")
    assert "location ~ ^/repos/[0-9]+/issues/sync$" in text
    assert "proxy_read_timeout 300s;" in text
