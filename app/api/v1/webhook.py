from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import verify_github_signature
from app.core.settings import get_settings
from app.crud import webhook_delivery as delivery_crud
from app.database.connect import get_db

router = APIRouter(tags=["webhook"])


@router.post("/api/v1/github-callback/")
async def github_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
):
    settings = get_settings()
    body = await request.body()
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    if not verify_github_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if not x_github_delivery or not x_github_event:
        raise HTTPException(status_code=400, detail="Missing GitHub delivery headers")

    if x_github_event == "ping":
        return {"status": "pong"}

    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if x_github_event not in {"issues", "pull_request"}:
        return {"status": "ignored"}

    existing = delivery_crud.get(db, x_github_delivery)
    if existing is not None:
        return {"status": "duplicate"}

    repo = payload.get("repository") or {}
    action = payload.get("action")
    delivery_crud.create_queued(
        db,
        delivery_id=x_github_delivery,
        event=x_github_event,
        action=action if isinstance(action, str) else None,
        repository_id=int(repo["id"]) if isinstance(repo.get("id"), int) else None,
        payload=payload,
    )
    from fastapi.responses import JSONResponse

    return JSONResponse({"status": "queued"}, status_code=status.HTTP_202_ACCEPTED)
