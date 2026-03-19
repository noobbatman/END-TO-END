"""Document pipeline: OCR → classify → extract → line items → LLM enrich → validate → score → package."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.classification.hybrid_classifier import HybridDocumentClassifier
from app.core.config import get_settings
from app.extraction.factory import get_extractor
from app.extraction.line_items import extract_line_items
from app.ocr.factory import get_ocr_provider
from app.pipelines.confidence import ConfidenceScorer
from app.utils.validators import run_validators


class DocumentPipeline:
    def __init__(self) -> None:
        settings = get_settings()
        self.ocr_provider = get_ocr_provider()
        self.classifier   = HybridDocumentClassifier()
        self.scorer       = ConfidenceScorer(settings.low_confidence_threshold)
        self.settings     = settings

    def run(self, path: str) -> dict[str, Any]:
        # 1. OCR
        ocr_result = self.ocr_provider.extract(path)

        # 2. Classify
        classification = self.classifier.classify(ocr_result.text)
        extractor      = get_extractor(classification.label)

        # 3. Extract header fields
        extracted       = extractor.extract(ocr_result)
        snippets        = extracted.metadata.get("field_snippets", {})
        required_fields = extracted.metadata.get("required_fields", [])
        page_map        = extracted.metadata.get("field_page_map", {})
        bbox_map        = extracted.metadata.get("field_bbox_map", {})

        # 4. Line item extraction (invoice & receipt)
        line_items: list[dict] = []
        if extracted.document_type in ("invoice", "receipt"):
            line_items = extract_line_items(ocr_result, stored_path=path)

        # 5. Optional LLM enrichment for low-confidence fields
        fields = dict(extracted.fields)
        try:
            from app.services.llm_extraction_service import LLMExtractionService
            llm_svc = LLMExtractionService()
            if llm_svc._enabled:
                # Pre-score to identify which fields to enrich
                pre_scored = self.scorer.score_fields(
                    fields=fields,
                    snippets=snippets,
                    ocr_confidence=ocr_result.metadata.get("average_confidence", 0.0),
                    classifier_confidence=classification.confidence,
                    required_fields=required_fields,
                )
                fields = llm_svc.enrich_fields(
                    document_type=extracted.document_type,
                    ocr_text=ocr_result.text,
                    current_fields=fields,
                    field_confidences=pre_scored,
                )
        except Exception:
            pass  # LLM enrichment is best-effort

        # 6. Field validation
        validation_results = run_validators(extracted.document_type, fields)

        # 7. Confidence scoring
        ocr_confidence   = ocr_result.metadata.get("average_confidence", 0.0)
        field_confidences= self.scorer.score_fields(
            fields=fields,
            snippets=snippets,
            ocr_confidence=ocr_confidence,
            classifier_confidence=classification.confidence,
            required_fields=required_fields,
        )
        document_confidence = self.scorer.score_document(
            field_confidences=field_confidences,
            classifier_confidence=classification.confidence,
            ocr_confidence=ocr_confidence,
            required_fields=required_fields,
        )

        # 8. Annotate low-confidence fields with page evidence
        low_conf_fields = []
        for fc in field_confidences:
            if fc.requires_review:
                val_reason = next(
                    (v["reason"] for v in validation_results
                     if v["field"] == fc.name and not v["valid"]),
                    None,
                )
                low_conf_fields.append({
                    **fc.model_dump(),
                    "page_number":       page_map.get(fc.name, 1),
                    "bbox":              bbox_map.get(fc.name),
                    "validation_reason": val_reason,
                })

        export_payload = {
            "document_type":      extracted.document_type,
            "schema_version":     "2.0",
            "source_file":        Path(path).name,
            "fields":             fields,
            "line_items":         line_items,
            "entities":           extracted.entities,
            "tables":             extracted.tables,
            "field_confidences":  [fc.model_dump() for fc in field_confidences],
            "document_confidence": document_confidence,
            "validation_results": validation_results,
        }

        return {
            "document_type":         extracted.document_type,
            "classifier_confidence": classification.confidence,
            "document_confidence":   document_confidence,
            "ocr_text":              ocr_result.text,
            "ocr_metadata":          ocr_result.metadata,
            "raw_payload": {
                "classification": asdict(classification),
                "fields":         fields,
                "entities":       extracted.entities,
                "tables":         extracted.tables,
                "line_items":     line_items,
            },
            "normalized_payload": {
                "fields":     fields,
                "entities":   extracted.entities,
                "tables":     extracted.tables,
                "line_items": line_items,
            },
            "export_payload": export_payload,
            "extraction_metadata": {
                "field_snippets":     snippets,
                "required_fields":    required_fields,
                "pipeline_version":   self.settings.pipeline_version,
                "validation_results": validation_results,
                "line_item_count":    len(line_items),
            },
            "low_confidence_fields": low_conf_fields,
        }
