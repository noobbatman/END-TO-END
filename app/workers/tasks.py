"""Celery tasks: document processing, webhook dispatch, batch processing, email ingestion."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import webhooks_dispatched_total
from app.db.session import SessionLocal
from app.services.pipeline_service import PipelineService
from app.workers.celery_app import celery_app

logger   = get_logger(__name__)
settings = get_settings()


# ── Document processing ───────────────────────────────────────────────────────

def _run_processing(self: Any, document_id: str) -> dict:
    db = SessionLocal()
    try:
        logger.info("processing_document", extra={"document_id": document_id, "task_id": self.request.id})
        service = PipelineService(db)
        return service.process_document(document_id)
    except SoftTimeLimitExceeded:
        logger.error("task_soft_time_limit_exceeded", extra={"document_id": document_id})
        raise
    finally:
        db.close()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_kwargs={"max_retries": 3},
    name="app.workers.tasks.process_document_task",
)
def process_document_task(self, document_id: str) -> dict:
    return _run_processing(self, document_id)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 5},
    name="app.workers.tasks.process_document_high_priority",
)
def process_document_high_priority(self, document_id: str) -> dict:
    return _run_processing(self, document_id)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.batch_process_task",
)
def batch_process_task(self, document_ids: list[str]) -> dict:
    results: dict[str, str] = {}
    for doc_id in document_ids:
        task = process_document_task.apply_async(args=[doc_id])
        results[doc_id] = str(task.id)
        logger.info("batch_enqueued", extra={"document_id": doc_id, "task_id": task.id})
    return {"enqueued": results}


# ── Webhook dispatch ──────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    autoretry_for=(httpx.RequestError, httpx.HTTPStatusError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": settings.webhook_max_retries},
    name="app.workers.tasks.dispatch_webhook_task",
)
def dispatch_webhook_task(self, webhook_id: str, event: str, payload: dict) -> dict:
    from app.db.models import Webhook, WebhookStatus
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        webhook = db.get(Webhook, webhook_id)
        if not webhook or webhook.status != WebhookStatus.active:
            return {"skipped": True}

        body    = json.dumps({"event": event, "payload": payload})
        headers = {"Content-Type": "application/json", "X-DocintelEvent": event}
        if webhook.secret:
            sig = hmac.new(webhook.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-DocintelSignature"] = f"sha256={sig}"

        with httpx.Client(timeout=settings.webhook_timeout_seconds) as client:
            resp = client.post(webhook.url, content=body, headers=headers)
            resp.raise_for_status()

        webhook.last_triggered_at = datetime.now(timezone.utc)
        webhook.failure_count     = 0
        db.commit()
        webhooks_dispatched_total.labels(event=event, success="true").inc()
        logger.info("webhook_dispatched", extra={"webhook_id": webhook_id, "status": resp.status_code})
        return {"status": resp.status_code}

    except Exception as exc:
        if db.is_active:
            wh = db.get(Webhook, webhook_id)
            if wh:
                wh.failure_count += 1
                db.commit()
        webhooks_dispatched_total.labels(event=event, success="false").inc()
        logger.error("webhook_failed", extra={"webhook_id": webhook_id, "error": str(exc)})
        raise
    finally:
        db.close()


# ── Email ingestion ───────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.workers.tasks.poll_email_task",
)
def poll_email_task(self) -> dict:
    """Poll configured IMAP mailbox and enqueue found attachments."""
    from app.services.email_ingestion_service import EmailIngestionService
    from app.db.models import Document, DocumentStatus

    svc = EmailIngestionService()
    if not svc.is_configured():
        return {"skipped": True, "reason": "Email not configured"}

    attachments = svc.poll()
    if not attachments:
        return {"enqueued": 0}

    db = SessionLocal()
    enqueued: list[dict] = []
    try:
        for att in attachments:
            doc = Document(
                filename=att["original_filename"],
                stored_path=att["stored_path"],
                content_type=att["content_type"],
                status=DocumentStatus.queued,
                pipeline_version=settings.pipeline_version,
                tags={
                    "source":  "email",
                    "sender":  att.get("sender", ""),
                    "subject": att.get("subject", ""),
                },
            )
            db.add(doc)
            db.flush()
            task = process_document_task.delay(doc.id)
            enqueued.append({"document_id": doc.id, "task_id": str(task.id)})
        db.commit()
    finally:
        db.close()

    return {"enqueued": len(enqueued), "documents": enqueued}
