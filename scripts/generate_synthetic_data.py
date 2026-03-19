import json
from pathlib import Path


def build_samples() -> list[dict]:
    return [
        {
            "document_type": "invoice",
            "text": "Invoice Number INV-1001 Invoice Date 2025-07-01 Due Date 2025-07-15 "
            "Vendor Acme Services Bill To Globex Total $1250.00 Tax $100.00 Subtotal $1150.00",
            "expected": {
                "invoice_number": "INV-1001",
                "total_amount": 1250.0,
            },
        },
        {
            "document_type": "bank_statement",
            "text": "Statement Period 2025-07-01 to 2025-07-31 Account Number 99887766 "
            "Opening Balance $5000.00 Closing Balance $4500.00 Available Balance $4500.00",
            "expected": {
                "account_number": "99887766",
                "closing_balance": 4500.0,
            },
        },
    ]


if __name__ == "__main__":
    output_dir = Path("data/eval")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "synthetic_samples.json"
    output_path.write_text(json.dumps(build_samples(), indent=2), encoding="utf-8")
    print(f"Wrote synthetic dataset to {output_path}")

