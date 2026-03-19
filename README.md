# Document Intelligence Platform v0.3.0

An end-to-end, production-grade document processing pipeline built from a research-backed analysis of what open-source alternatives (MinerU, deepdoctection, InvoiceNet), commercial platforms (Rossum, Stampli, ABBYY FlexiCapture), and community requests on GitHub and Reddit are actually doing and demanding.

**upload → OCR → classify → extract → line items → validate → score → review → export**

---

## Baseline Benchmark Results

> 80 synthetic PDFs — 40 invoices · 40 bank statements · clean / multipage / noisy variants  
> Full methodology: [`evaluation/REPORT.md`](evaluation/REPORT.md)

| Metric | Score |
|---|---|
| Classification — clean & multipage docs | **100%** |
| Classification — noisy/OCR-artefact docs | 0% *(current weak spot; treated honestly as a baseline gap)* |
| Overall classification accuracy | **75%** |
| Field extraction macro-avg F1 | **0.694** |
| `closing_balance` F1 | **1.000** |
| `total_amount` / `account_number` / `invoice_date` F1 | **0.857** |
| Average document confidence | **0.660** |
| Low-confidence field rate | **38.5%** |
| Avg classification latency | **0.13 ms** |

---

## What makes this different from other open-source projects

Based on a survey of 30+ GitHub repos and commercial platform comparisons:

| Feature | Most OSS projects | This platform |
|---|---|---|
| Line item extraction | ❌ header fields only | ✅ pdfplumber + regex |
| Duplicate / fraud detection | ❌ | ✅ hash + invoice collision + anomaly + velocity |
| LLM fallback extraction | ❌ | ✅ Claude Haiku for null fields |
| Email ingestion (IMAP) | ❌ | ✅ poll + auto-enqueue |
| CSV / Excel export | ❌ JSON only | ✅ CSV, XLSX, JSON batch |
| PO matching (3-way) | ❌ | ✅ PO number + vendor + amount |
| Page-level review evidence | ❌ | ✅ page_number + bbox + validation_reason |
| Cross-field consistency scoring | ❌ | ✅ subtotal+tax≈total, closing≈available |
| Field format validators | ❌ | ✅ dates, amounts, IBAN, invoice ID patterns |
| Active learning feedback loop | ❌ | ✅ CorrectionRecord + export endpoint |
| Tenant-aware access controls | ❌ | ✅ tenant-scoped document, review, PO, dedup, and export routes |
| Request rate limiting | ❌ or proxy-only | ✅ app-level per-minute limits for default + upload endpoints |
| HTTP request metrics | ❌ | ✅ Prometheus counters + latency histograms on every request |
| Priority processing queues | ❌ | ✅ normal / high / webhooks |
| Synthetic evaluation dataset | ❌ | ✅ 80 synthetic PDFs with ground truth |

---

## Architecture

```
Client
  │
  ▼
FastAPI  /api/v1
  ├── POST /documents/upload              → 202, Celery task (normal | high priority)
  ├── GET  /documents?status=&type=       → paginated + filtered
  ├── GET  /documents/search?q=           → filename + OCR text search
  ├── GET  /documents/{id}/result         → extraction + line items + validation
  ├── GET  /documents/{id}/status         → lightweight poll
  ├── POST /documents/{id}/reprocess      → re-run pipeline
  ├── DELETE /documents/{id}              → soft delete
  │
  ├── GET  /reviews/pending               → tasks with page_number + bbox + validation_reason
  ├── POST /reviews/{id}/decision         → submit correction (stored for active learning)
  │
  ├── POST /purchase-orders               → register a PO
  ├── GET  /purchase-orders               → list POs
  ├── POST /purchase-orders/match/{id}    → run 3-way PO match
  ├── GET  /purchase-orders/match/{id}    → get match result
  │
  ├── POST /deduplication/{id}/check      → hash + collision + anomaly + velocity check
  │
  ├── GET  /exports/csv                   → flat CSV download
  ├── GET  /exports/xlsx                  → styled Excel workbook
  ├── GET  /exports/json                  → full extraction payloads
  │
  ├── GET  /analytics/metrics/overview    → per-tenant document counts + confidence
  ├── GET  /analytics/metrics/ocr-distribution
  ├── GET  /analytics/corrections         → tenant-scoped reviewer corrections export
  ├── GET  /analytics/corrections/stats   → tenant-scoped field failure stats
  ├── GET  /analytics/audit/tenant        → tenant-scoped audit log
  │
  ├── POST /webhooks                      → register (HMAC-SHA256 signed events)
  └── GET  /health/live  /health/ready
  │
  ▼
Celery Workers
  ├── documents.high   — dedicated priority queue
  ├── documents.normal — 2 replicas × 4 concurrency
  ├── webhooks         — 8 concurrency
  └── poll_email_task  — scheduled IMAP polling (when configured)
       │
       ▼
  DocumentPipeline
    1. OCR         (Tesseract | PaddleOCR)
    2. Classify    (TF-IDF + keyword density + regex — 4 types)
    3. Extract     (invoice | bank_statement | receipt | contract)
    4. Line Items  (pdfplumber tables → regex fallback)
    5. LLM enrich  (Claude Haiku — optional, for null fields only)
    6. Validate    (dates, amounts, IBAN, cross-field consistency)
    7. Score       (5-signal: extraction + OCR + classifier + format + consistency)
    8. Review      (low-confidence → ReviewTask with page evidence)
  │
  ▼
PostgreSQL · Redis · MinIO/S3
```

HTTP runtime controls:
- app-level in-memory rate limiting is enforced via middleware, using `RATE_LIMIT_DEFAULT_PER_MINUTE` and `RATE_LIMIT_UPLOAD_PER_MINUTE`
- Prometheus request metrics are emitted for every request via `docintel_http_requests_total` and `docintel_http_request_duration_seconds`
- for multi-instance production deployments, the current limiter should be replaced with a shared Redis-backed implementation at the edge or middleware layer

---

## Local Run

### Fastest local path: Docker Compose

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local-up.ps1 -Rebuild
```

Manual equivalent:

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
```

Open:

| Service | URL |
|---|---|
| Main app UI | http://localhost:8000/ |
| API docs | http://localhost:8000/docs |
| Celery Flower | http://localhost:5555 |
| Grafana | http://localhost:3000 (admin/admin) |
| MinIO | http://localhost:9001 (minioadmin/minioadmin) |
| Review UI | http://localhost:8501 |

Run the sample flow:

```bash
bash scripts/demo_run.sh
```

Stop services:

```bash
docker compose down
```

### Running directly on your machine

If you want to run FastAPI/Celery outside Docker, start PostgreSQL and Redis locally and use:

```bash
cp .env.localhost.example .env
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
alembic upgrade head
uvicorn app.main:app --reload
```

In another shell:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=INFO --queues=documents.normal
```

---

## Line Item Extraction

Every invoice now returns structured line items alongside header fields:

```json
{
  "fields": { "invoice_number": "INV-001", "total_amount": 1200.0 },
  "line_items": [
    { "description": "Consulting Services", "quantity": 5, "unit_price": 200.0, "line_total": 1000.0 },
    { "description": "Software License",    "quantity": 1, "unit_price": 200.0, "line_total":  200.0 }
  ]
}
```

Strategy: pdfplumber table extraction on digital PDFs → regex line-by-line parser fallback.

---

## Duplicate & Fraud Detection

```bash
curl -X POST http://localhost:8000/api/v1/deduplication/{id}/check
```

Returns a risk report with four independent signals:

| Signal | Trigger |
|---|---|
| `exact_duplicate` | Byte-for-byte SHA-256 hash match |
| `invoice_number_collision` | Same invoice number already in database |
| `amount_anomaly` | Total >3σ from vendor historical mean (min 5 past invoices) |
| `vendor_velocity` | Vendor submitted >20 invoices in last 24 hours |

Risk levels: `clean` / `low` / `medium` / `high`.

---

## PO Matching (3-Way Match)

```bash
# Register a PO
curl -X POST http://localhost:8000/api/v1/purchase-orders \
  -H "Content-Type: application/json" \
  -d '{"po_number":"PO-2024-001","vendor_name":"Acme Ltd","total_amount":1200.0}'

# Match an invoice against registered POs
curl -X POST http://localhost:8000/api/v1/purchase-orders/match/{document_id}
```

Match logic: PO number exact match (40pts) + vendor name fuzzy match (30pts) + total amount ±1% tolerance (30pts).
Result: `matched` (≥85%) / `partial` (50–85%) / `unmatched` with per-field discrepancies.

---

## LLM Fallback Extraction

Enable optional Anthropic-backed fallback extraction to recover fields that regex missed:

```env
LLM_EXTRACTION_ENABLED=true
```

When enabled, null low-signal fields are sent to Anthropic with a structured prompt. Only null fields are re-extracted, so the LLM does not overwrite successful deterministic extraction.

---

## Email Ingestion

```env
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_ADDRESS=ap@yourcompany.com
EMAIL_PASSWORD=your-app-password
EMAIL_FOLDER=INBOX
```

Schedule the Celery task:
```python
celery_app.conf.beat_schedule = {
    "poll-email": {"task": "app.workers.tasks.poll_email_task", "schedule": 300.0}
}
```

---

## Exports

```bash
# Flat CSV — paste directly into Excel or accounting system
curl "http://localhost:8000/api/v1/exports/csv?document_type=invoice&status=completed" \
  -o invoices.csv

# Styled Excel workbook with frozen header row
curl "http://localhost:8000/api/v1/exports/xlsx" -o documents.xlsx

# Full extraction payloads as JSON array
curl "http://localhost:8000/api/v1/exports/json" -o batch.json
```

---

## Active Learning

Every reviewer correction is stored:

```bash
# Export corrections as labelled training data
curl "http://localhost:8000/api/v1/analytics/corrections?document_type=invoice"

# See which fields fail most
curl "http://localhost:8000/api/v1/analytics/corrections/stats"
```

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest -v --tb=short
```

| File | Cases |
|---|---|
| `test_documents_api.py` | 9 |
| `test_review_api.py` | 5 |
| `test_webhooks_api.py` | 5 |
| `test_extractor_pipeline.py` | 9 |
| `test_classifier.py` | 9 |
| `test_confidence.py` | 8 |
| `test_validators.py` | 18 |
| `test_analytics_api.py` | 7 |
| `test_new_features.py` | 12 |
| **Total** | **82** |

---

## Database Migrations

```bash
alembic upgrade head        # apply all (0001 → 0002 → 0003)
alembic current             # check state
alembic downgrade -1        # rollback one step
```

| Migration | Adds |
|---|---|
| `0001` | All core tables + indexes |
| `0002` | Page evidence on review_tasks, CorrectionRecord, validation_results, UTC timestamps |
| `0003` | PurchaseOrder + POMatch tables |

---

## Known Limitations

| Limitation | Next Step |
|---|---|
| Noisy OCR: 0% classification | Enable `LLM_EXTRACTION_ENABLED=true` for recovery; long-term: LayoutLM/Donut |
| `invoice_number` F1=0.00 on noisy | Character-level normalisation (`0→O` reversal) before classification |
| `subtotal` recall=50% | Layout variation; line-item sum can derive it when direct extraction fails |
| No real IMAP test | Requires live mailbox; unit test with mock available |
| Noisy synthetic docs still classify poorly | Current baseline is weak on OCR-artefact-heavy samples; improve with stronger layout-aware classification |
