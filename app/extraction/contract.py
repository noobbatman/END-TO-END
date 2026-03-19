"""Contract / agreement extractor."""
from typing import Any

from app.extraction.base import ExtractionOutput, Extractor
from app.extraction.entities import extract_entities
from app.ocr.base import OCRResult
from app.utils.text import find_snippet, regex_search


class ContractExtractor(Extractor):
    def extract(self, ocr_result: OCRResult) -> ExtractionOutput:
        text = ocr_result.text

        effective_date = regex_search(
            r"effective\s+(?:as\s+of\s+)?date\s*[:#]?\s*([A-Za-z0-9,\-\/ ]+)", text
        )
        party_a = regex_search(
            r"(?:between|party\s+a|first\s+party)\s*[:#]?\s*([A-Za-z0-9 &,\.\-]+)", text
        )
        party_b = regex_search(
            r"(?:and|party\s+b|second\s+party)\s*[:#]?\s*([A-Za-z0-9 &,\.\-]+)", text
        )
        governing_law = regex_search(
            r"governing\s+law\s*[:#]?\s*(?:shall\s+be\s+)?(?:the\s+laws?\s+of\s+)?([A-Za-z ,]+)", text
        )
        termination_date = regex_search(
            r"termination\s+date\s*[:#]?\s*([A-Za-z0-9,\-\/ ]+)", text
        )
        contract_value = regex_search(
            r"(?:contract\s+value|total\s+value|consideration)\s*[:#]?\s*([$€£]?\s?[\d,]+(?:\.\d{2})?)", text
        )

        fields: dict[str, Any] = {
            "effective_date": effective_date,
            "party_a": party_a,
            "party_b": party_b,
            "governing_law": governing_law,
            "termination_date": termination_date,
            "contract_value": contract_value,
        }
        snippets = {
            name: find_snippet(text, str(value)) if value is not None else None
            for name, value in fields.items()
        }
        entities = extract_entities(ocr_result)
        return ExtractionOutput(
            document_type="contract",
            fields=fields,
            entities=entities,
            tables=[],
            metadata={
                "field_snippets": snippets,
                "required_fields": ["effective_date", "party_a", "party_b"],
            },
        )
