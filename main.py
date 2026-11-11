from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from app.api.router import api_router, include_v1_routes
from app.core.exceptions import LoginRedirect
from app.core.logging import setup_logging
from app.middleware.access_log import AccessLogMiddleware

setup_logging()
include_v1_routes()

app = FastAPI(title="GitHub Workflow")
app.add_middleware(AccessLogMiddleware)
app.include_router(api_router)


@app.exception_handler(LoginRedirect)
async def login_redirect_handler(_request: Request, _exc: LoginRedirect) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
