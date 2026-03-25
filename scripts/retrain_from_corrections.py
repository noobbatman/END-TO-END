#!/usr/bin/env python3
"""scripts/retrain_from_corrections.py — Close the active learning loop."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/docintel")

from sqlalchemy import select

from app.db.models import CorrectionRecord, ExtractionResult
from app.db.session import SessionLocal


def _truncate(text: str | None, max_chars: int = 4000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    head = text[: max_chars * 3 // 4]
    tail = text[-(max_chars // 4):]
    return head + "\n...[truncated]...\n" + tail


def build_training_record(record: CorrectionRecord, ocr_text: str | None) -> dict:
    return {
        "id": record.id,
        "document_type": record.document_type,
        "field_name": record.field_name,
        "ocr_text": _truncate(ocr_text),
        "ocr_snippet": record.ocr_snippet or "",
        "original_value": record.original_value,
        "corrected_value": record.corrected_value,
        "pipeline_version": record.pipeline_version,
        "reviewed_at": record.created_at.isoformat(),
    }


def print_report(records: list[CorrectionRecord]) -> None:
    by_field: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    by_version: dict[str, int] = defaultdict(int)
    changed = sum(1 for r in records if r.original_value != r.corrected_value)

    for r in records:
        by_field[r.field_name] += 1
        by_type[r.document_type] += 1
        by_version[r.pipeline_version] += 1

    print(f"\n{'=' * 60}")
    print(f"  Correction report — {len(records)} total, {changed} value-changed")
    print(f"{'=' * 60}")
    print("\nBy document type:")
    for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {k:<25} {v:>5}")
    print("\nBy field (top 15):")
    for k, v in sorted(by_field.items(), key=lambda x: -x[1])[:15]:
        print(f"  {k:<30} {v:>5}")
    print("\nBy pipeline version:")
    for k, v in sorted(by_version.items(), key=lambda x: -x[1]):
        print(f"  {k:<20} {v:>5}")
    print()


def run(
    document_type: str | None = None,
    since: datetime | None = None,
    output_path: Path = Path("data/training/corrections.jsonl"),
    dry_run: bool = False,
) -> None:
    db = SessionLocal()
    try:
        stmt = select(CorrectionRecord).order_by(CorrectionRecord.created_at.asc())
        if document_type:
            stmt = stmt.where(CorrectionRecord.document_type == document_type)
        if since:
            stmt = stmt.where(CorrectionRecord.created_at >= since)

        records = list(db.scalars(stmt))
        if not records:
            print("No correction records found.")
            return

        print_report(records)
        if dry_run:
            print("Dry-run mode — no file written.")
            return

        doc_ids = list({r.document_id for r in records})
        ocr_map: dict[str, str | None] = {}
        for chunk_start in range(0, len(doc_ids), 500):
            chunk = doc_ids[chunk_start: chunk_start + 500]
            rows = db.execute(
                select(ExtractionResult.document_id, ExtractionResult.ocr_text).where(
                    ExtractionResult.document_id.in_(chunk)
                )
            ).all()
            for doc_id, ocr_text in rows:
                ocr_map[doc_id] = ocr_text

        output_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with output_path.open("w", encoding="utf-8") as fh:
            for record in records:
                ocr_text = ocr_map.get(record.document_id)
                training_record = build_training_record(record, ocr_text)
                fh.write(json.dumps(training_record, ensure_ascii=False) + "\n")
                written += 1

        print(f"Wrote {written} training records to {output_path}")
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Export reviewer corrections as training data.")
    ap.add_argument("--document-type", default=None, help="Filter to one document type")
    ap.add_argument("--since", default=None, help="Only include corrections after this date (YYYY-MM-DD)")
    ap.add_argument("--output", default="data/training/corrections.jsonl", help="Output JSONL file path")
    ap.add_argument("--dry-run", action="store_true", help="Print report only, don't write file")
    args = ap.parse_args()

    since_dt: datetime | None = None
    if args.since:
        since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    run(
        document_type=args.document_type,
        since=since_dt,
        output_path=Path(args.output),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
