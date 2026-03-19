# MVP Definition

## Document Types

### Implemented

- `invoice`
- `bank_statement`

### Planned Extensions

- `kyc_form`
- `insurance_claim`
- `lease_document`
- `medical_form`

## JSON Output Schemas

### Invoice

```json
{
  "document_type": "invoice",
  "schema_version": "1.0",
  "source_file": "invoice_001.pdf",
  "fields": {
    "invoice_number": "INV-001",
    "invoice_date": "2025-08-01",
    "due_date": "2025-08-15",
    "vendor_name": "Acme Supplies Ltd",
    "customer_name": "Northwind Retail LLC",
    "subtotal": 1200.0,
    "tax": 96.0,
    "total_amount": 1296.0
  },
  "entities": [],
  "tables": [],
  "field_confidences": [],
  "document_confidence": 0.89
}
```

### Bank Statement

```json
{
  "document_type": "bank_statement",
  "schema_version": "1.0",
  "source_file": "statement_001.pdf",
  "fields": {
    "account_number": "****1234",
    "statement_period": "2025-07-01 to 2025-07-31",
    "opening_balance": 4021.15,
    "closing_balance": 3588.21,
    "available_balance": 3588.21
  },
  "entities": [],
  "tables": [],
  "field_confidences": [],
  "document_confidence": 0.85
}
```

## Database Schema

### `documents`

- Core document metadata and processing status
- One row per uploaded file

### `extraction_results`

- OCR text
- raw extractor output
- normalized payload
- export payload
- OCR and extraction metadata

### `review_tasks`

- Low-confidence field queue
- Source snippet and proposed value

### `review_decisions`

- Reviewer corrections
- Comments for audit and future model improvement

### `audit_logs`

- Immutable process trail for upload, processing, failures, and review actions

## API Summary

- Upload: `POST /api/v1/documents/upload`
- Batch upload: `POST /api/v1/documents/upload/batch`
- Poll/list: `GET /api/v1/documents`
- Detail: `GET /api/v1/documents/{document_id}`
- Result: `GET /api/v1/documents/{document_id}/result`
- Export file: `GET /api/v1/documents/{document_id}/export`
- History: `GET /api/v1/documents/{document_id}/history`
- Reprocess: `POST /api/v1/documents/{document_id}/reprocess`
- Review queue: `GET /api/v1/reviews/queue`
- Review decision: `POST /api/v1/reviews/{task_id}/decision`
