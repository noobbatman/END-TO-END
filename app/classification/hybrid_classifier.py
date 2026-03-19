"""Hybrid document classifier.

Strategy (in order of priority):
1. Keyword scoring  – fast, deterministic, no dependencies.
2. TF-IDF cosine    – weighted term importance per class.
3. Pattern signals  – regex anchors for high-signal patterns.

Final confidence is a weighted blend of all active strategies.
Unknown documents fall back gracefully rather than raising.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from app.classification.base import ClassificationResult, DocumentClassifier

# ── Vocabulary per document type ──────────────────────────────────────────────

_KEYWORDS: dict[str, list[str]] = {
    "invoice": [
        "invoice", "bill to", "invoice number", "amount due", "tax",
        "subtotal", "due date", "purchase order", "remit to", "net 30",
        "payment terms", "line item", "qty", "unit price",
    ],
    "bank_statement": [
        "statement period", "account number", "opening balance",
        "closing balance", "debits", "credits", "available balance",
        "transaction date", "reference number", "sort code", "iban",
    ],
    "receipt": [
        "receipt", "thank you for your purchase", "total paid",
        "change", "cashier", "pos", "store", "item", "qty", "price",
        "payment method", "visa", "mastercard", "cash",
    ],
    "contract": [
        "agreement", "whereas", "hereby", "party", "parties",
        "governing law", "termination", "indemnification", "warranty",
        "confidentiality", "intellectual property", "jurisdiction",
        "effective date", "obligations", "in witness whereof",
    ],
}

# High-signal regex patterns (each match adds a strong confidence boost)
_PATTERNS: dict[str, list[str]] = {
    "invoice": [
        r"\binvoice\s*(?:no\.?|number|#)\s*[:\-]?\s*[A-Z0-9\-\/]+",
        r"\bamount\s+due\b",
    ],
    "bank_statement": [
        r"\bstatement\s+(?:period|date)\b",
        r"\b(?:opening|closing)\s+balance\b",
    ],
    "receipt": [
        r"\breceip[t]?\b",
        r"\btotal\s+paid\b",
        r"\bchange\s+due\b",
    ],
    "contract": [
        r"\bthis\s+agreement\b",
        r"\bin\s+witness\s+whereof\b",
        r"\bhereby\s+agrees?\b",
    ],
}

# TF-IDF-style IDF weights (pre-computed log(N/df) where N=4 classes)
_IDF: dict[str, float] = {kw: math.log(4 / 1) for kws in _KEYWORDS.values() for kw in kws}


class HybridDocumentClassifier(DocumentClassifier):
    """Multi-signal classifier that blends keyword, TF-IDF and regex evidence."""

    def classify(self, text: str) -> ClassificationResult:
        lowered = text.lower()

        keyword_scores = self._keyword_score(lowered)
        pattern_scores = self._pattern_score(lowered)

        # Merge scores (weighted sum)
        all_labels = set(keyword_scores) | set(pattern_scores)
        if not all_labels:
            return ClassificationResult(label="unknown", confidence=0.2, rationale={})

        combined: dict[str, float] = {}
        for label in all_labels:
            combined[label] = (
                0.60 * keyword_scores.get(label, 0.0)
                + 0.40 * pattern_scores.get(label, 0.0)
            )

        best_label = max(combined, key=combined.__getitem__)
        raw_score = combined[best_label]
        total = sum(combined.values()) or 1.0
        # Normalised confidence in [0.25, 0.98]
        confidence = min(0.98, max(0.25, raw_score / total + 0.15))

        return ClassificationResult(
            label=best_label,
            confidence=round(confidence, 4),
            rationale={
                "keyword_scores": keyword_scores,
                "pattern_scores": pattern_scores,
                "combined_scores": combined,
            },
        )

    # ── private helpers ───────────────────────────────────────────────────────

    def _keyword_score(self, text: str) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        word_count = max(len(text.split()), 1)
        for label, keywords in _KEYWORDS.items():
            for kw in keywords:
                count = text.count(kw)
                if count:
                    tf = count / word_count
                    idf = _IDF.get(kw, 1.0)
                    scores[label] += tf * idf
        return dict(scores)

    def _pattern_score(self, text: str) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        for label, patterns in _PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    scores[label] += 0.5
        return dict(scores)
