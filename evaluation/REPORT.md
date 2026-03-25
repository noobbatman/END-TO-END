# Benchmark Evaluation Report (v2 — with normalization fixes)

> **Dataset:** 80 documents

## Classification

| Overall accuracy | **100.0%** |
|---|---|
| clean docs | 100.0% |
| multipage docs | 100.0% |
| noisy docs | 100.0% |

## Field Extraction

| Field | F1 | TP | FP | FN |
|---|---|---|---|---|
| `account_number` | **0.961** | 37 | 0 | 3 |
| `available_balance` | **0.857** | 30 | 0 | 10 |
| `closing_balance` | **1.000** | 40 | 0 | 0 |
| `customer_name` | **0.771** | 27 | 3 | 13 |
| `invoice_date` | **1.000** | 40 | 0 | 0 |
| `invoice_number` | **0.950** | 38 | 2 | 2 |
| `opening_balance` | **1.000** | 40 | 0 | 0 |
| `statement_period` | **0.857** | 30 | 0 | 10 |
| `subtotal` | **0.857** | 30 | 0 | 10 |
| `tax` | **0.857** | 30 | 0 | 10 |
| `total_amount` | **0.750** | 30 | 10 | 10 |
| `vendor_name` | **1.000** | 40 | 0 | 0 |

**Macro-average F1: 0.905**
