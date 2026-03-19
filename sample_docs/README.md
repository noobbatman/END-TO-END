# Sample Documents

Four synthetic PDF documents that exercise every document type supported by the pipeline.

| File | Type | Key Fields |
|---|---|---|
| `sample_invoice.pdf` | `invoice` | Invoice No, Total, VAT, Due Date, Vendor, Customer |
| `sample_bank_statement.pdf` | `bank_statement` | Account No, IBAN, Opening/Closing Balance, Transactions |
| `sample_receipt.pdf` | `receipt` | Store, Total Paid, Payment Method, Receipt No |
| `sample_contract.pdf` | `contract` | Party A/B, Effective Date, Contract Value, Governing Law |

## Quick demo

```bash
# Start the stack
docker compose up --build -d

# Upload all samples and check results
for f in sample_docs/*.pdf; do
  echo "=== Uploading $f ==="
  curl -s -X POST http://localhost:8000/api/v1/documents/upload \
    -F "file=@$f" | jq '{id: .document.id, status: .document.status, task: .task_id}'
done

# Poll a document result (replace <ID>)
curl -s http://localhost:8000/api/v1/documents/<ID>/result | jq .
```

## Expected classification results

All four documents are designed to produce confident (>0.70) classifications.
The invoice and bank statement contain the highest-signal keyword density.
