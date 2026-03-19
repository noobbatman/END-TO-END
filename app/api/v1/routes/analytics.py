"""Analytics, active-learning corrections, and per-tenant metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_dependency, get_optional_tenant, require_api_key
from app.db.models import (
    AuditLog, CorrectionRecord, Document, DocumentStatus,
    ExtractionResult, ReviewTask, ReviewStatus,
)
from app.services.correction_service import CorrectionService

router = APIRouter(dependencies=[Depends(require_api_key)])


# ── Per-tenant metrics ────────────────────────────────────────────────────────

@router.get("/metrics/overview")
def overview_metrics(
    tenant_id: str | None = Depends(get_optional_tenant),
    db: Session = Depends(db_dependency),
) -> dict:
    """Aggregate counts — optionally scoped to a tenant."""
    q = select(Document)
    if tenant_id:
        q = q.where(Document.tenant_id == tenant_id)
    q = q.where(Document.deleted_at.is_(None))

    docs = list(db.scalars(q))
    by_status = {}
    by_type   = {}
    conf_sum  = 0.0
    conf_count= 0

    for d in docs:
        by_status[d.status] = by_status.get(d.status, 0) + 1
        if d.document_type:
            by_type[d.document_type] = by_type.get(d.document_type, 0) + 1
        if d.document_confidence is not None:
            conf_sum   += d.document_confidence
            conf_count += 1

    pending_review_stmt = (
        select(func.count(ReviewTask.id))
        .join(Document, Document.id == ReviewTask.document_id)
        .where(ReviewTask.status == ReviewStatus.pending, Document.deleted_at.is_(None))
    )
    if tenant_id:
        pending_review_stmt = pending_review_stmt.where(Document.tenant_id == tenant_id)
    pending_review = db.scalar(pending_review_stmt) or 0

    corrections_stmt = (
        select(func.count(CorrectionRecord.id))
        .join(Document, Document.id == CorrectionRecord.document_id)
        .where(Document.deleted_at.is_(None))
    )
    if tenant_id:
        corrections_stmt = corrections_stmt.where(Document.tenant_id == tenant_id)
    total_corrections = db.scalar(corrections_stmt) or 0

    return {
        "tenant_id":            tenant_id or "all",
        "total_documents":      len(docs),
        "by_status":            by_status,
        "by_document_type":     by_type,
        "avg_document_confidence": round(conf_sum / conf_count, 4) if conf_count else None,
        "pending_review_tasks": pending_review,
        "total_corrections":    total_corrections,
    }


@router.get("/metrics/ocr-distribution")
def ocr_distribution(
    tenant_id: str | None = Depends(get_optional_tenant),
    db: Session = Depends(db_dependency),
) -> dict:
    """OCR confidence distribution across processed documents."""
    stmt = (
        select(ExtractionResult.ocr_metadata)
        .join(Document, Document.id == ExtractionResult.document_id)
        .where(Document.deleted_at.is_(None))
    )
    if tenant_id:
        stmt = stmt.where(Document.tenant_id == tenant_id)
    rows = db.scalars(stmt)
    buckets = {"<0.5": 0, "0.5-0.7": 0, "0.7-0.85": 0, "0.85-0.95": 0, ">0.95": 0}
    for meta in rows:
        conf = meta.get("average_confidence", 0.0) if meta else 0.0
        if conf < 0.5:         buckets["<0.5"] += 1
        elif conf < 0.7:       buckets["0.5-0.7"] += 1
        elif conf < 0.85:      buckets["0.7-0.85"] += 1
        elif conf < 0.95:      buckets["0.85-0.95"] += 1
        else:                  buckets[">0.95"] += 1
    return {"tenant_id": tenant_id or "all", "buckets": buckets}


# ── Active-learning corrections ───────────────────────────────────────────────

@router.get("/corrections")
def list_corrections(
    tenant_id:     str | None = Depends(get_optional_tenant),
    document_type: str | None = Query(default=None),
    field_name:    str | None = Query(default=None),
    limit:         int        = Query(default=100, ge=1, le=1000),
    db: Session = Depends(db_dependency),
) -> list[dict]:
    """Export reviewer corrections as labelled data for retraining."""
    svc = CorrectionService(db)
    return svc.export_corrections(
        tenant_id=tenant_id,
        document_type=document_type,
        field_name=field_name,
    )[:limit]


@router.get("/corrections/stats")
def correction_stats(
    tenant_id: str | None = Depends(get_optional_tenant),
    db: Session = Depends(db_dependency),
) -> dict:
    """Aggregate correction statistics — which fields fail most often."""
    return CorrectionService(db).correction_stats(tenant_id=tenant_id)


@router.get("/audit/tenant")
def tenant_audit(
    tenant_id: str | None = Depends(get_optional_tenant),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(db_dependency),
) -> list[dict]:
    """Tenant-scoped audit log."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    logs = list(db.scalars(stmt))
    return [
        {"id": l.id, "event_type": l.event_type, "actor": l.actor,
         "payload": l.payload, "created_at": l.created_at.isoformat()}
        for l in logs
    ]
