"""Webhook management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.api.deps import db_dependency, require_api_key
from app.db.models import WebhookEvent
from app.services.webhook_service import WebhookService

router = APIRouter(dependencies=[Depends(require_api_key)])


class WebhookCreate(BaseModel):
    name: str
    url: HttpUrl
    event: WebhookEvent
    secret: str | None = None


class WebhookRead(BaseModel):
    id: str
    name: str
    url: str
    event: str
    status: str
    failure_count: int

    model_config = {"from_attributes": True}


@router.get("", response_model=list[WebhookRead])
def list_webhooks(db: Session = Depends(db_dependency)) -> list[WebhookRead]:
    return [WebhookRead.model_validate(w) for w in WebhookService(db).list_webhooks()]


@router.post("", response_model=WebhookRead, status_code=status.HTTP_201_CREATED)
def register_webhook(body: WebhookCreate, db: Session = Depends(db_dependency)) -> WebhookRead:
    wh = WebhookService(db).register(
        name=body.name,
        url=str(body.url),
        event=str(body.event),
        secret=body.secret,
    )
    return WebhookRead.model_validate(wh)


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def deactivate_webhook(webhook_id: str, db: Session = Depends(db_dependency)) -> Response:
    wh = WebhookService(db).deactivate(webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
