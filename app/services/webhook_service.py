"""Webhook registration and dispatch service."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Webhook, WebhookEvent, WebhookStatus


class WebhookService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register(self, name: str, url: str, event: str, secret: str | None = None) -> Webhook:
        webhook = Webhook(name=name, url=url, event=event, secret=secret)
        self.db.add(webhook)
        self.db.commit()
        self.db.refresh(webhook)
        return webhook

    def list_webhooks(self) -> list[Webhook]:
        return list(self.db.scalars(select(Webhook).order_by(Webhook.created_at.desc())))

    def get(self, webhook_id: str) -> Webhook | None:
        return self.db.get(Webhook, webhook_id)

    def deactivate(self, webhook_id: str) -> Webhook | None:
        wh = self.get(webhook_id)
        if wh:
            wh.status = WebhookStatus.inactive
            self.db.commit()
        return wh

    def dispatch_event(self, event: str, payload: dict) -> list[str]:
        """Fire-and-forget: enqueue tasks for all active webhooks matching *event*."""
        from app.workers.tasks import dispatch_webhook_task

        hooks = list(
            self.db.scalars(
                select(Webhook).where(
                    Webhook.event == event, Webhook.status == WebhookStatus.active
                )
            )
        )
        task_ids: list[str] = []
        for hook in hooks:
            task = dispatch_webhook_task.apply_async(args=[hook.id, event, payload])
            task_ids.append(str(task.id))
        return task_ids
