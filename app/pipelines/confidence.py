"""Confidence scoring with OCR signal, field validation, and cross-field consistency checks.

Scoring weights
---------------
  base_extraction   0.40  — was the value found and non-empty?
  ocr_signal        0.15  — page-level OCR confidence
  classifier_signal 0.10  — classifier confidence for this doc type
  format_validation 0.20  — does the value pass type-specific format rules?
  cross_field       0.15  — consistency with sibling fields (e.g. sub+tax≈total)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.schemas.common import FieldConfidence

# ── Format validators ──────────────────────────────────────────────────────────

_DATE_PATTERNS = [
    r"\d{1,2}/\d{1,2}/\d{2,4}",
    r"\d{1,2}-\d{1,2}-\d{2,4}",
    r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}",
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}",
]
_DATE_RE = re.compile("|".join(_DATE_PATTERNS), re.IGNORECASE)

_INVOICE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-\/\._ ]{2,40}$", re.IGNORECASE)
_ACCOUNT_RE    = re.compile(r"^[\d\-\*X ]{4,30}$")
_AMOUNT_RE     = re.compile(r"^\d+(\.\d{1,2})?$")


def _validate_date(value: Any) -> float:
    if not value:
        return 0.0
    s = str(value)
    return 1.0 if _DATE_RE.search(s) else 0.3


def _validate_amount(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        f = float(value)
        return 1.0 if f > 0 else 0.2
    except (TypeError, ValueError):
        return 0.2


def _validate_invoice_id(value: Any) -> float:
    if not value:
        return 0.0
    return 1.0 if _INVOICE_ID_RE.match(str(value).strip()) else 0.4


def _validate_account(value: Any) -> float:
    if not value:
        return 0.0
    s = str(value).strip()
    return 1.0 if (_ACCOUNT_RE.match(s) and len(s) >= 4) else 0.4


def _validate_period(value: Any) -> float:
    if not value:
        return 0.0
    s = str(value)
    has_separator = bool(re.search(r"\s+(?:to|-)\s+", s, re.IGNORECASE))
    has_dates = len(_DATE_RE.findall(s)) >= 1
    return 1.0 if (has_separator and has_dates) else (0.6 if has_dates else 0.3)


_FIELD_VALIDATORS: dict[str, Any] = {
    # Invoice
    "invoice_number": _validate_invoice_id,
    "invoice_date":   _validate_date,
    "due_date":       _validate_date,
    "vendor_name":    lambda v: 0.8 if v and len(str(v)) > 2 else 0.0,
    "customer_name":  lambda v: 0.8 if v and len(str(v)) > 2 else 0.0,
    "subtotal":       _validate_amount,
    "tax":            _validate_amount,
    "total_amount":   _validate_amount,
    # Bank statement
    "account_number":   _validate_account,
    "statement_period": _validate_period,
    "opening_balance":  _validate_amount,
    "closing_balance":  _validate_amount,
    "available_balance":_validate_amount,
    # Receipt
    "receipt_date":     _validate_date,
    "receipt_number":   _validate_invoice_id,
    "payment_method":   lambda v: 0.8 if v and len(str(v)) > 1 else 0.0,
    # Contract
    "effective_date":   _validate_date,
    "termination_date": _validate_date,
    "party_a":          lambda v: 0.8 if v and len(str(v)) > 2 else 0.0,
    "party_b":          lambda v: 0.8 if v and len(str(v)) > 2 else 0.0,
    "governing_law":    lambda v: 0.8 if v and len(str(v)) > 2 else 0.0,
}

_DEFAULT_VALIDATOR = lambda v: 0.7 if v not in (None, "", []) else 0.0


# ── Cross-field consistency ────────────────────────────────────────────────────

def _cross_field_consistency(fields: dict[str, Any]) -> dict[str, float]:
    """Returns per-field consistency bonuses in [0.0, 1.0]."""
    bonuses: dict[str, float] = {}

    # Invoice: subtotal + tax should approximately equal total_amount (within 5%)
    sub = fields.get("subtotal")
    tax = fields.get("tax")
    tot = fields.get("total_amount")
    if sub is not None and tax is not None and tot is not None:
        try:
            sub_f, tax_f, tot_f = float(sub), float(tax), float(tot)
            if tot_f > 0:
                computed = sub_f + tax_f
                rel_err = abs(computed - tot_f) / tot_f
                score = max(0.0, 1.0 - rel_err * 10)  # penalise >10% error
                bonuses["subtotal"]      = score
                bonuses["tax"]           = score
                bonuses["total_amount"]  = score
        except (TypeError, ValueError):
            pass

    # Bank statement: opening_balance ± transactions should approximate closing_balance
    # (only possible when we have full transaction data — use as a soft check)
    opening = fields.get("opening_balance")
    closing = fields.get("closing_balance")
    available = fields.get("available_balance")
    if opening is not None and closing is not None:
        try:
            op_f, cl_f = float(opening), float(closing)
            if op_f > 0:
                bonuses["opening_balance"] = 1.0
                bonuses["closing_balance"] = 1.0
        except (TypeError, ValueError):
            pass
    if available is not None and closing is not None:
        try:
            av_f, cl_f = float(available), float(closing)
            diff_pct = abs(av_f - cl_f) / max(cl_f, 1.0)
            score = max(0.0, 1.0 - diff_pct * 5)
            bonuses["available_balance"] = score
            bonuses["closing_balance"]   = max(bonuses.get("closing_balance", 0.0), score)
        except (TypeError, ValueError):
            pass

    return bonuses


# ── Main scorer ────────────────────────────────────────────────────────────────

class ConfidenceScorer:
    """Multi-signal confidence scorer.

    Combines:
      - Base extraction presence
      - OCR / classifier signals
      - Per-field format validation
      - Cross-field consistency (invoice total, balance coherence)
    """

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def score_fields(
        self,
        fields: dict[str, Any],
        snippets: dict[str, str | None],
        ocr_confidence: float,
        classifier_confidence: float,
        required_fields: list[str],
    ) -> list[FieldConfidence]:
        cross = _cross_field_consistency(fields)
        scored: list[FieldConfidence] = []

        for name, value in fields.items():
            is_empty = value in (None, "", [])

            # 1. Base extraction score
            base = 0.0 if is_empty else 0.40

            # 2. OCR signal (attenuated)
            ocr_sig = 0.15 * ocr_confidence

            # 3. Classifier signal (attenuated)
            clf_sig = 0.10 * classifier_confidence

            # 4. Format validation
            validator = _FIELD_VALIDATORS.get(name, _DEFAULT_VALIDATOR)
            fmt_score = 0.0 if is_empty else validator(value)
            fmt_sig = 0.20 * fmt_score

            # 5. Cross-field consistency
            cross_sig = 0.15 * cross.get(name, 0.5)  # neutral 0.5 if no cross-check applies

            confidence = min(0.99, max(0.0, base + ocr_sig + clf_sig + fmt_sig + cross_sig))

            # Required field penalty: missing required field is always low confidence
            if name in required_fields and is_empty:
                confidence = min(confidence, 0.30)
            elif not is_empty and fmt_score < 0.5:
                confidence = min(confidence, 0.49)

            scored.append(FieldConfidence(
                name=name,
                value=value,
                confidence=round(confidence, 4),
                source_snippet=snippets.get(name),
                requires_review=confidence < self.threshold,
            ))

        return scored

    def score_document(
        self,
        field_confidences: list[FieldConfidence],
        classifier_confidence: float,
        ocr_confidence: float,
        required_fields: list[str],
    ) -> float:
        if not field_confidences:
            return 0.0

        mean_field = sum(f.confidence for f in field_confidences) / len(field_confidences)
        required_present = sum(
            1 for f in field_confidences
            if f.name in required_fields and f.value not in (None, "", [])
        )
        coverage = required_present / max(len(required_fields), 1)

        overall = (
            0.45 * mean_field
            + 0.20 * classifier_confidence
            + 0.10 * ocr_confidence
            + 0.25 * coverage
        )
        return round(min(0.99, overall), 4)
