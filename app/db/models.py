"""SQLAlchemy ORM models — all timestamps are timezone-aware UTC."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────

class DocumentStatus(StrEnum):
    uploaded        = "uploaded"
    queued          = "queued"
    processing      = "processing"
    review_required = "review_required"
    completed       = "completed"
    failed          = "failed"


class ReviewStatus(StrEnum):
    pending   = "pending"
    completed = "completed"
    dismissed = "dismissed"


class AuditEventType(StrEnum):
    document_uploaded           = "document_uploaded"
    document_deleted            = "document_deleted"
    processing_started          = "processing_started"
    processing_completed        = "processing_completed"
    processing_failed           = "processing_failed"
    review_task_created         = "review_task_created"
    review_decision_submitted   = "review_decision_submitted"
    document_reprocessed        = "document_reprocessed"
    webhook_dispatched          = "webhook_dispatched"
    webhook_failed              = "webhook_failed"
    correction_exported         = "correction_exported"


class WebhookEvent(StrEnum):
    processing_completed = "processing_completed"
    processing_failed    = "processing_failed"
    review_required      = "review_required"


class WebhookStatus(StrEnum):
    active   = "active"
    inactive = "inactive"


# ── Models ────────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_status",        "status"),
        Index("ix_documents_document_type", "document_type"),
        Index("ix_documents_created_at",    "created_at"),
        Index("ix_documents_tenant_id",     "tenant_id"),
        Index("ix_documents_deleted_at",    "deleted_at"),
    )

    id:                    Mapped[str]            = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    filename:              Mapped[str]            = mapped_column(String(255),  nullable=False)
    stored_path:           Mapped[str]            = mapped_column(String(1000), nullable=False)
    content_type:          Mapped[str]            = mapped_column(String(120),  nullable=False)
    status:                Mapped[str]            = mapped_column(String(40),   default=DocumentStatus.uploaded)
    document_type:         Mapped[str | None]     = mapped_column(String(80),   nullable=True)
    pipeline_version:      Mapped[str]            = mapped_column(String(40),   nullable=False)
    classifier_confidence: Mapped[float | None]   = mapped_column(Float,        nullable=True)
    document_confidence:   Mapped[float | None]   = mapped_column(Float,        nullable=True)
    error_message:         Mapped[str | None]     = mapped_column(Text,         nullable=True)
    tenant_id:             Mapped[str | None]     = mapped_column(String(80),   nullable=True)
    tags:                  Mapped[dict[str, Any]] = mapped_column(JSON,         default=dict)
    deleted_at:            Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    created_at:            Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:            Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    extraction_result: Mapped[ExtractionResult | None] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    review_tasks: Mapped[list[ReviewTask]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ExtractionResult(Base):
    __tablename__ = "extraction_results"

    id:                   Mapped[str]            = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id:          Mapped[str]            = mapped_column(ForeignKey("documents.id"), unique=True)
    ocr_text:             Mapped[str]            = mapped_column(Text,   default="")
    raw_payload:          Mapped[dict[str, Any]] = mapped_column(JSON,   default=dict)
    normalized_payload:   Mapped[dict[str, Any]] = mapped_column(JSON,   default=dict)
    export_payload:       Mapped[dict[str, Any]] = mapped_column(JSON,   default=dict)
    ocr_metadata:         Mapped[dict[str, Any]] = mapped_column(JSON,   default=dict)
    extraction_metadata:  Mapped[dict[str, Any]] = mapped_column(JSON,   default=dict)
    # Validation results from the validator pipeline
    validation_results:   Mapped[list[dict]]     = mapped_column(JSON,   default=list)
    created_at:           Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:           Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    document: Mapped[Document] = relationship(back_populates="extraction_result")


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (Index("ix_review_tasks_status", "status"),)

    id:              Mapped[str]            = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id:     Mapped[str]            = mapped_column(ForeignKey("documents.id"))
    field_name:      Mapped[str]            = mapped_column(String(255), nullable=False)
    proposed_value:  Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    original_value:  Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_snippet:  Mapped[str | None]     = mapped_column(Text, nullable=True)
    confidence:      Mapped[float]          = mapped_column(Float, nullable=False)
    status:          Mapped[str]            = mapped_column(String(40), default=ReviewStatus.pending)
    # Page-level evidence (Priority 4)
    page_number:     Mapped[int | None]     = mapped_column(Integer, nullable=True)
    bbox:            Mapped[list | None]    = mapped_column(JSON, nullable=True)  # [x0,y0,x1,y1]
    validation_reason: Mapped[str | None]  = mapped_column(Text, nullable=True)
    created_at:      Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:      Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    document:  Mapped[Document]          = relationship(back_populates="review_tasks")
    decisions: Mapped[list[ReviewDecision]] = relationship(
        back_populates="review_task", cascade="all, delete-orphan"
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id:               Mapped[str]            = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_task_id:   Mapped[str]            = mapped_column(ForeignKey("review_tasks.id"))
    reviewer_name:    Mapped[str]            = mapped_column(String(255), nullable=False)
    corrected_value:  Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comment:          Mapped[str | None]     = mapped_column(Text, nullable=True)
    created_at:       Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=_utcnow)

    review_task: Mapped[ReviewTask] = relationship(back_populates="decisions")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_event_type", "event_type"),)

    id:          Mapped[str]            = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str]            = mapped_column(ForeignKey("documents.id"))
    event_type:  Mapped[str]            = mapped_column(String(80), nullable=False)
    actor:       Mapped[str]            = mapped_column(String(255), default="system")
    payload:     Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tenant_id:   Mapped[str | None]     = mapped_column(String(80), nullable=True, index=True)
    created_at:  Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[Document] = relationship(back_populates="audit_logs")


class Webhook(Base):
    __tablename__ = "webhooks"
    __table_args__ = (
        UniqueConstraint("url", "event", name="uq_webhook_url_event"),
        Index("ix_webhooks_status", "status"),
    )

    id:                 Mapped[str]          = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name:               Mapped[str]          = mapped_column(String(255), nullable=False)
    url:                Mapped[str]          = mapped_column(String(2048), nullable=False)
    event:              Mapped[str]          = mapped_column(String(80), nullable=False)
    secret:             Mapped[str | None]   = mapped_column(String(255), nullable=True)
    status:             Mapped[str]          = mapped_column(String(40), default=WebhookStatus.active)
    failure_count:      Mapped[int]          = mapped_column(Integer, default=0)
    last_triggered_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:         Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_utcnow)


class CorrectionRecord(Base):
    """Active-learning feedback store — captures reviewer corrections for retraining."""
    __tablename__ = "correction_records"
    __table_args__ = (Index("ix_corrections_document_type", "document_type"),)

    id:               Mapped[str]  = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id:      Mapped[str]  = mapped_column(ForeignKey("documents.id"))
    document_type:    Mapped[str]  = mapped_column(String(80), nullable=False)
    field_name:       Mapped[str]  = mapped_column(String(255), nullable=False)
    original_value:   Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value:  Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_snippet:      Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_name:    Mapped[str]  = mapped_column(String(255), nullable=False)
    pipeline_version: Mapped[str]  = mapped_column(String(40), nullable=False)
    created_at:       Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
