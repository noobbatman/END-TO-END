"""Invoice field extractor — regex + validation normalisation."""
from __future__ import annotations

import re
from typing import Any

from app.extraction.base import ExtractionOutput, Extractor
from app.extraction.entities import extract_entities
from app.extraction.table_extractor import TableExtractor
from app.ocr.base import OCRResult
from app.utils.text import find_snippet, normalize_amount, regex_search
from app.utils.validators import parse_date, parse_amount


class InvoiceExtractor(Extractor):
    def __init__(self) -> None:
        self.table_extractor = TableExtractor()

    def extract(self, ocr_result: OCRResult) -> ExtractionOutput:
        text = ocr_result.text

        # ── Invoice number — broad pattern to handle noisy OCR ──────────────
        invoice_number = (
            regex_search(r"inv(?:oice)?\s*(?:number|no\.?|#|num)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/\._ ]{1,39})", text)
            or regex_search(r"(?:l\s*N\s*V|lnv0ice|invoice)\s*N(?:o|0)\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]+)", text)
            or regex_search(r"\b((?:INV|BILL|SI|REF|DOC)-\d{4}-\d+)\b", text)
        )
        if invoice_number:
            invoice_number = invoice_number.strip().upper()

        # ── Dates ────────────────────────────────────────────────────────────
        raw_inv_date = (
            regex_search(r"inv(?:oice)?\s+date\s*[:#]?\s*([A-Za-z0-9,\-\/ ]+)", text)
            or regex_search(r"(?:dated?|date\s*issued)\s*[:#]?\s*([A-Za-z0-9,\-\/ ]+)", text)
        )
        raw_due_date = regex_search(r"due\s+date\s*[:#]?\s*([A-Za-z0-9,\-\/ ]+)", text)

        invoice_date = parse_date(raw_inv_date) or raw_inv_date
        due_date     = parse_date(raw_due_date) or raw_due_date

        # ── Parties ──────────────────────────────────────────────────────────
        vendor_name   = regex_search(r"(?:from|seller|vendor|fr0m)\s*[:#]?\s*([A-Za-z0-9&,\.\- ]{3,60})", text)
        customer_name = regex_search(r"(?:bill\s+to|bi11\s+t0|customer)\s*[:#]?\s*([A-Za-z0-9&,\.\- ]{3,60})", text)

        # ── Amounts — try multiple label variants ─────────────────────────────
        raw_subtotal = (
            regex_search(r"subt(?:otal)?\s*[:#]?\s*([$€£GBP]?\s?[\d,]+\.\d{2})", text)
            or regex_search(r"(?:net\s+amount|excl\.?\s+(?:vat|tax))\s*[:#]?\s*([$€£GBP]?\s?[\d,]+\.\d{2})", text)
        )
        raw_tax = (
            regex_search(r"(?:vat|tax|gst)\s*(?:\(\d+%\))?\s*[:#]?\s*([$€£GBP]?\s?[\d,]+\.\d{2})", text)
            or regex_search(r"TA\s*X\s+([\d,]+\.\d{2})", text)
        )
        raw_total = (
            regex_search(r"(?:total\s+due|amount\s+due|invoice\s+total|t0tal\s+due|t0tal)\s*[:#]?\s*([$€£GBP]?\s?[\d,]+\.\d{2})", text)
            or regex_search(r"(?:total|t0tal)\s*[:#]?\s*([$€£GBP]?\s?[\d,]+\.\d{2})", text)
        )

        subtotal = parse_amount(raw_subtotal) or normalize_amount(raw_subtotal)
        tax      = parse_amount(raw_tax)      or normalize_amount(raw_tax)
        total    = parse_amount(raw_total)    or normalize_amount(raw_total)

        # If only total found and tax known, derive subtotal
        if total is not None and tax is not None and subtotal is None:
            subtotal = round(total - tax, 2)

        fields: dict[str, Any] = {
            "invoice_number": invoice_number,
            "invoice_date":   invoice_date,
            "due_date":       due_date,
            "vendor_name":    vendor_name,
            "customer_name":  customer_name,
            "subtotal":       subtotal,
            "tax":            tax,
            "total_amount":   total,
        }

        tables        = self.table_extractor.extract_from_ocr_words(ocr_result)
        entities      = extract_entities(ocr_result)
        field_snippets= {
            name: find_snippet(text, str(value)) if value is not None else None
            for name, value in fields.items()
        }
        # Page-number map — all fields on page 1 unless multi-page
        page_count = ocr_result.metadata.get("page_count", 1)
        page_map   = {name: 1 for name in fields}
        if page_count > 1:
            # Summary fields (totals) tend to be on the last page
            for f in ("subtotal", "tax", "total_amount"):
                page_map[f] = page_count

        return ExtractionOutput(
            document_type="invoice",
            fields=fields,
            entities=entities,
            tables=tables,
            metadata={
                "field_snippets":  field_snippets,
                "required_fields": ["invoice_number", "total_amount"],
                "field_page_map":  page_map,
            },
        )


# ── Line item injection (called by pipeline after basic extraction) ────────────
# The extract() method above fills header fields.
# Line items are extracted separately and merged in by DocumentPipeline
# because we need the stored_path (unavailable inside the extractor).
