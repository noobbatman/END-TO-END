"""Purchase Order (PO) matching service.

Three-way match: Invoice ↔ Purchase Order ↔ (optional) Goods Receipt.

This is the top enterprise differentiator — every major AP platform
(Rossum, Stampli, SAP, BILL) lists PO matching as a core feature.

Architecture:
  - PurchaseOrder model stores registered POs (vendor, number, amount, line items)
  - match() compares extracted invoice fields against stored POs
  - Returns match status: matched / partial / unmatched + discrepancies
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import String, Float, JSON, DateTime, ForeignKey, Index, select, and_
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session

from app.db.base import Base
from app.db.models import Document


def _utcnow(): return datetime.now(timezone.utc)


# ── PurchaseOrder model ────────────────────────────────────────────────────────

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_po_number", "po_number"),
        Index("ix_po_vendor", "vendor_name"),
        Index("ix_po_tenant", "tenant_id"),
    )

    id:          Mapped[str]          = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    po_number:   Mapped[str]          = mapped_column(String(255), nullable=False)
    vendor_name: Mapped[str]          = mapped_column(String(255), nullable=False)
    total_amount:Mapped[float | None] = mapped_column(Float, nullable=True)
    currency:    Mapped[str]          = mapped_column(String(10), default="GBP")
    line_items:  Mapped[list]         = mapped_column(JSON, default=list)
    status:      Mapped[str]          = mapped_column(String(40), default="open")
    tenant_id:   Mapped[str | None]   = mapped_column(String(80), nullable=True)
    created_at:  Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:  Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class POMatch(Base):
    __tablename__ = "po_matches"

    id:              Mapped[str]   = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id:     Mapped[str]   = mapped_column(ForeignKey("documents.id"))
    po_id:           Mapped[str | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    match_status:    Mapped[str]   = mapped_column(String(40), default="unmatched")
    match_score:     Mapped[float] = mapped_column(Float, default=0.0)
    discrepancies:   Mapped[list]  = mapped_column(JSON, default=list)
    matched_fields:  Mapped[dict]  = mapped_column(JSON, default=dict)
    created_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Matching logic ─────────────────────────────────────────────────────────────

def _normalize_vendor(name: str | None) -> str:
    if not name:
        return ""
    # Strip Ltd/Inc/Corp/LLC suffixes for fuzzy matching
    s = re.sub(r"\b(?:ltd|limited|inc|corp|corporation|llc|plc|gmbh|srl|sarl|bv)\b", "", name, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


def _amount_match(a: float | None, b: float | None, tolerance: float = 0.01) -> bool:
    if a is None or b is None:
        return False
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tolerance


class POMatchingService:
    """Match invoices against registered purchase orders."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── PO management ─────────────────────────────────────────────────────────

    def register_po(
        self,
        po_number: str,
        vendor_name: str,
        total_amount: float | None = None,
        currency: str = "GBP",
        line_items: list | None = None,
        tenant_id: str | None = None,
    ) -> PurchaseOrder:
        po = PurchaseOrder(
            po_number=po_number,
            vendor_name=vendor_name,
            total_amount=total_amount,
            currency=currency,
            line_items=line_items or [],
            tenant_id=tenant_id,
        )
        self.db.add(po)
        self.db.commit()
        self.db.refresh(po)
        return po

    def list_pos(self, tenant_id: str | None = None) -> list[PurchaseOrder]:
        stmt = select(PurchaseOrder)
        if tenant_id:
            stmt = stmt.where(PurchaseOrder.tenant_id == tenant_id)
        return list(self.db.scalars(stmt.order_by(PurchaseOrder.created_at.desc())))

    # ── Matching ───────────────────────────────────────────────────────────────

    def match(self, document: Document) -> POMatch:
        """Find the best PO match for a processed document and store the result."""
        result = document.extraction_result
        if not result:
            return self._save_match(document.id, None, "unmatched", 0.0, [], {})

        fields       = result.export_payload.get("fields", {})
        inv_vendor   = fields.get("vendor_name")
        inv_total    = fields.get("total_amount")
        inv_po_ref   = fields.get("purchase_order")
        inv_currency = fields.get("currency", "GBP")

        # Candidate POs: match by PO reference number first
        candidates: list[PurchaseOrder] = []
        if inv_po_ref:
            exact = list(self.db.scalars(
                select(PurchaseOrder).where(PurchaseOrder.po_number == str(inv_po_ref))
            ))
            candidates.extend(exact)

        # Also search by vendor name fuzzy match
        norm_vendor = _normalize_vendor(inv_vendor)
        if norm_vendor:
            all_pos = list(self.db.scalars(select(PurchaseOrder)))
            for po in all_pos:
                if po not in candidates:
                    if norm_vendor in _normalize_vendor(po.vendor_name) or \
                       _normalize_vendor(po.vendor_name) in norm_vendor:
                        candidates.append(po)

        if not candidates:
            return self._save_match(document.id, None, "unmatched", 0.0,
                                    [{"field": "po", "issue": "No matching PO found for this vendor"}], {})

        # Score each candidate
        best_po   = None
        best_score= 0.0
        best_discrepancies: list[dict] = []
        best_matched: dict = {}

        for po in candidates:
            score, discrepancies, matched = self._score_match(
                po=po,
                inv_vendor=inv_vendor,
                inv_total=float(inv_total) if inv_total else None,
                inv_po_ref=inv_po_ref,
                inv_currency=inv_currency,
                inv_line_items=result.export_payload.get("line_items", []),
            )
            if score > best_score:
                best_score        = score
                best_po           = po
                best_discrepancies= discrepancies
                best_matched      = matched

        status = (
            "matched"  if best_score >= 0.85 else
            "partial"  if best_score >= 0.50 else
            "unmatched"
        )
        return self._save_match(
            document.id,
            best_po.id if best_po else None,
            status, best_score, best_discrepancies, best_matched,
        )

    def get_match(self, document_id: str) -> POMatch | None:
        return self.db.scalar(
            select(POMatch).where(POMatch.document_id == document_id)
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    def _score_match(
        self,
        po: PurchaseOrder,
        inv_vendor: str | None,
        inv_total: float | None,
        inv_po_ref: str | None,
        inv_currency: str,
        inv_line_items: list,
    ) -> tuple[float, list[dict], dict]:
        score        = 0.0
        discrepancies: list[dict] = []
        matched: dict = {}

        # PO number match (40 points)
        if inv_po_ref and inv_po_ref == po.po_number:
            score += 0.40
            matched["po_number"] = po.po_number
        elif inv_po_ref:
            discrepancies.append({
                "field":    "purchase_order",
                "invoice":  inv_po_ref,
                "po":       po.po_number,
                "issue":    "PO number mismatch",
            })

        # Vendor name match (30 points)
        inv_norm = _normalize_vendor(inv_vendor)
        po_norm  = _normalize_vendor(po.vendor_name)
        if inv_norm and po_norm and (inv_norm in po_norm or po_norm in inv_norm):
            score += 0.30
            matched["vendor_name"] = po.vendor_name
        elif inv_vendor:
            discrepancies.append({
                "field":   "vendor_name",
                "invoice": inv_vendor,
                "po":      po.vendor_name,
                "issue":   "Vendor name mismatch",
            })

        # Total amount match (30 points)
        if _amount_match(inv_total, po.total_amount):
            score += 0.30
            matched["total_amount"] = po.total_amount
        elif inv_total is not None and po.total_amount is not None:
            pct_diff = abs(inv_total - po.total_amount) / max(po.total_amount, 1) * 100
            discrepancies.append({
                "field":    "total_amount",
                "invoice":  inv_total,
                "po":       po.total_amount,
                "issue":    f"Amount differs by {pct_diff:.1f}%",
            })

        return score, discrepancies, matched

    def _save_match(
        self, document_id: str, po_id: str | None,
        status: str, score: float, discrepancies: list, matched: dict,
    ) -> POMatch:
        # Remove previous match if exists
        existing = self.get_match(document_id)
        if existing:
            self.db.delete(existing)
            self.db.flush()

        match = POMatch(
            document_id=document_id,
            po_id=po_id,
            match_status=status,
            match_score=round(score, 3),
            discrepancies=discrepancies,
            matched_fields=matched,
        )
        self.db.add(match)
        self.db.commit()
        self.db.refresh(match)
        return match
