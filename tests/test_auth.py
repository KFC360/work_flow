from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import user as user_crud


def test_token_success(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    resp = client.post("/token", data={"username": "admin", "password": "admin-pass"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert COOKIE_NAME not in resp.cookies
    payload = decode_access_token(body["access_token"])
    assert payload["sub"] == "admin"
    assert "jti" in payload


def test_token_wrong_password(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    resp = client.post("/token", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_token_disabled(client: TestClient, db: Session) -> None:
    user = user_crud.ensure_admin_user(db)
    assert user is not None
    user.disabled = True
    db.commit()
    resp = client.post("/token", data={"username": "admin", "password": "admin-pass"})
    assert resp.status_code == 400
    assert "Inactive" in resp.json()["detail"]


def test_login_cookie_redirect(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "admin-pass"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert COOKIE_NAME in resp.cookies


def test_login_wrong_password_html(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    resp = client.post("/login", data={"username": "admin", "password": "nope"})
    assert resp.status_code == 200
    assert "用户名或口令不正确" in resp.text
    assert COOKIE_NAME not in resp.cookies


def test_login_disabled_html(client: TestClient, db: Session) -> None:
    user = user_crud.ensure_admin_user(db)
    assert user is not None
    user.disabled = True
    db.commit()
    resp = client.post("/login", data={"username": "admin", "password": "admin-pass"})
    assert resp.status_code == 200
    assert "账号已停用" in resp.text


def test_logout_requires_csrf(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    jti = decode_access_token(token)["jti"]
    client.cookies.set(COOKIE_NAME, token)
    resp = client.post("/logout", data={}, follow_redirects=False)
    assert resp.status_code == 403
    resp_ok = client.post(
        "/logout",
        data={"csrf_token": csrf_token_for_jti(jti)},
        follow_redirects=False,
    )
    assert resp_ok.status_code == 303
    assert resp_ok.headers["location"] == "/login"


def test_healthz_public(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_docs_no_jwt_required(client: TestClient) -> None:
    resp = client.get("/docs")
    assert resp.status_code == 200
