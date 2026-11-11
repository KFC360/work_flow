from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()


def include_v1_routes() -> None:
    from app.api.v1 import auth, companies, deliveries, issues, repos, settings, webhook

    api_router.include_router(auth.router)
    api_router.include_router(companies.router)
    api_router.include_router(repos.router)
    api_router.include_router(issues.router)
    api_router.include_router(settings.router)
    api_router.include_router(webhook.router)
    api_router.include_router(deliveries.router)
