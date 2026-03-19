# Benchmark Evaluation Report

> **Dataset:** 80 documents — 40 invoices · 40 bank statements  
> **Variants:** clean (50%), multipage (25%), noisy/low-quality (25%)

---

## 1  Document Classification

| Metric | Score |
|---|---|
| **Overall accuracy** | **75.0%** |
| Accuracy — Invoice | 75.0% |
| Accuracy — Bank Statement | 75.0% |
| Accuracy — clean docs | 100.0% |
| Accuracy — multipage docs | 100.0% |
| Accuracy — noisy docs | 0.0% |

---

## 2  Field Extraction — Precision / Recall / F1

| Field | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| `account_number` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |
| `available_balance` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |
| `closing_balance` | 1.000 | 1.000 | **1.000** | 40 | 0 | 0 |
| `customer_name` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |
| `invoice_date` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |
| `invoice_number` | 0.000 | 0.000 | **0.000** | 0 | 30 | 40 |
| `opening_balance` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |
| `statement_period` | 1.000 | 0.500 | **0.667** | 20 | 0 | 20 |
| `subtotal` | 0.000 | 0.000 | **0.000** | 0 | 0 | 40 |
| `tax` | 1.000 | 0.500 | **0.667** | 20 | 0 | 20 |
| `total_amount` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |
| `vendor_name` | 1.000 | 0.750 | **0.857** | 30 | 0 | 10 |

**Macro-average F1: 0.694**

---

## 3  Confidence Score Distribution

| Bucket | Count | % |
|---|---|---|
| <0.5 | 20 | 25% |
| 0.5-0.7 | 10 | 12% |
| 0.7-0.85 | 30 | 38% |
| 0.85-0.95 | 20 | 25% |
| >0.95 | 0 | 0% |

- **Avg document confidence:** 0.660
- **Avg OCR confidence (simulated):** 0.830
- **Low-confidence field rate:** 38.5%

---

## 4  Field Validation Pass Rates

| Field | Pass | Fail | Pass Rate |
|---|---|---|---|
| `account_number` | 30 | 10 | 75% |
| `available_balance` | 30 | 10 | 75% |
| `closing_balance` | 40 | 0 | 100% |
| `due_date` | 13 | 27 | 32% |
| `invoice_date` | 17 | 23 | 42% |
| `invoice_number` | 30 | 10 | 75% |
| `opening_balance` | 30 | 10 | 75% |
| `statement_period` | 20 | 20 | 50% |
| `subtotal` | 0 | 40 | 0% |
| `tax` | 20 | 20 | 50% |
| `total_amount` | 30 | 10 | 75% |

---

## 5  Performance

| Metric | Value |
|---|---|
| Avg classification latency | 0.131 ms |
| Samples evaluated | 80 |

---

## Methodology

- **Dataset:** 80 synthetic PDFs with hand-crafted ground truth (40 invoices, 40 bank statements).
- **Variants:** clean (standard layout), multipage (2-page with pagination), noisy (OCR-style character substitutions).
- **OCR simulation:** `pdfplumber` text layer extraction; confidence modelled at 0.88 (clean), 0.84 (multipage), 0.72 (noisy).
- **Classifier:** HybridDocumentClassifier — TF-IDF keyword density + regex pattern scoring (4 doc types).
- **Field matching:** exact for IDs, ±1% relative tolerance for amounts, case-insensitive substring for names.
- **Confidence scoring:** multi-signal — extraction presence (40%), OCR signal (15%), classifier signal (10%), format validation (20%), cross-field consistency (15%).
- **Validators:** date format, amount range, invoice ID pattern, account format, subtotal+tax≈total, closing≈available balance.
