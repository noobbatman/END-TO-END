#!/usr/bin/env python3
"""scripts/calibrate_confidence.py — Re-derive confidence scoring weights."""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_CURRENT = dict(W_BASE=0.40, W_OCR=0.15, W_CLF=0.10, W_FMT=0.20, W_CROSS=0.15)


def _classify_and_extract(text: str, doc_type: str) -> dict:
    from scripts.evaluate_v2 import classify, extract_bank_statement, extract_invoice, normalize_ocr_artifacts

    normalized = normalize_ocr_artifacts(text)
    _, clf_conf = classify(text)
    fields = extract_invoice(normalized) if doc_type == "invoice" else extract_bank_statement(normalized)
    return fields, clf_conf


_DATE_RE = re.compile(
    r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}",
    re.I,
)
_ACCT_RE = re.compile(r"^[\d\-\*X ]{4,30}$")

_FVAL = {
    "invoice_number": lambda v: 0.9 if v and re.match(r"^[A-Z0-9\-]{3,}$", str(v), re.I) else 0.3,
    "invoice_date": lambda v: 0.9 if v and _DATE_RE.search(str(v)) else 0.2,
    "due_date": lambda v: 0.9 if v and _DATE_RE.search(str(v)) else 0.2,
    "subtotal": lambda v: 0.9 if v and float(v) > 0 else 0.1,
    "tax": lambda v: 0.9 if v and float(v) > 0 else 0.1,
    "total_amount": lambda v: 0.9 if v and float(v) > 0 else 0.1,
    "account_number": lambda v: 0.9 if v and _ACCT_RE.match(str(v)) else 0.3,
    "statement_period": lambda v: (0.9 if re.search(r"\s+(?:to|-)\s+|/", str(v), re.I) else 0.3) if v else 0.0,
    "opening_balance": lambda v: 0.9 if v and float(v) > 0 else 0.1,
    "closing_balance": lambda v: 0.9 if v and float(v) > 0 else 0.1,
    "available_balance": lambda v: 0.9 if v and float(v) > 0 else 0.1,
}
_DEFAULT_FV = lambda v: 0.7 if v not in (None, "", []) else 0.0


def _compute_confidence(fields: dict, ocr_conf: float, clf_conf: float, weights: dict) -> dict[str, float]:
    W_BASE, W_OCR, W_CLF, W_FMT, W_CROSS = (
        weights["W_BASE"], weights["W_OCR"], weights["W_CLF"], weights["W_FMT"], weights["W_CROSS"]
    )
    cross: dict[str, float] = {}
    sub, tax, tot = fields.get("subtotal"), fields.get("tax"), fields.get("total_amount")
    if sub and tax and tot:
        try:
            err = abs((float(sub) + float(tax)) - float(tot)) / max(float(tot), 1)
            sc = max(0, 1 - err * 10)
            cross.update({"subtotal": sc, "tax": sc, "total_amount": sc})
        except Exception:
            pass

    result = {}
    for name, value in fields.items():
        empty = value in (None, "", [])
        base = 0.0 if empty else W_BASE
        fmt = (_FVAL.get(name, _DEFAULT_FV)(value) if not empty else 0.0)
        c = min(0.99, base + W_OCR * ocr_conf + W_CLF * clf_conf + W_FMT * fmt + W_CROSS * cross.get(name, 0.5))
        result[name] = c
    return result


def _value_match(pred, exp, field: str) -> bool:
    if pred is None and exp is None:
        return True
    if pred is None or exp is None:
        return False
    if any(k in field for k in ("amount", "balance", "subtotal", "tax", "total")):
        try:
            return abs(float(pred) - float(exp)) / max(abs(float(exp)), 1) < 0.01
        except Exception:
            pass
    p, e = str(pred).strip().upper(), str(exp).strip().upper()
    return p == e or e in p or p in e


def compute_mse(manifest_path: Path, weights: dict) -> float:
    samples = json.loads(manifest_path.read_text())
    errors: list[float] = []

    for sample in samples:
        doc_type = sample["document_type"]
        gt = {k: v for k, v in sample["ground_truth"].items() if k != "transactions"}
        fpath = Path(__file__).parents[1] / sample["file"]
        text = ""
        try:
            import pdfplumber

            with pdfplumber.open(str(fpath)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            text = fpath.stem.replace("_", " ")

        variant = sample["variant"]
        ocr_conf = 0.88 if variant == "clean" else (0.72 if variant == "noisy" else 0.84)

        try:
            fields, clf_conf = _classify_and_extract(text, doc_type)
        except Exception:
            continue

        confidences = _compute_confidence(fields, ocr_conf, clf_conf, weights)
        for fname, expected in gt.items():
            if fname not in fields:
                continue
            correct = 1.0 if _value_match(fields[fname], expected, fname) else 0.0
            pred_c = confidences.get(fname, 0.0)
            errors.append((pred_c - correct) ** 2)

    return sum(errors) / len(errors) if errors else 1.0


def grid_search(manifest_path: Path, step: float = 0.05) -> tuple[dict, float]:
    stops = [round(v, 2) for v in list(_range(0.0, 0.6 + step, step))]
    best_weights = _CURRENT.copy()
    best_mse = compute_mse(manifest_path, _CURRENT)
    checked = 0

    print(f"Baseline MSE (current weights): {best_mse:.6f}")
    print(f"Grid step: {step}  |  Searching weight combinations ...")

    for w_base, w_ocr, w_clf, w_fmt in itertools.product(stops, stops, stops, stops):
        w_cross = round(1.0 - w_base - w_ocr - w_clf - w_fmt, 4)
        if w_cross < 0 or w_cross > 0.6:
            continue
        weights = dict(W_BASE=w_base, W_OCR=w_ocr, W_CLF=w_clf, W_FMT=w_fmt, W_CROSS=w_cross)
        mse = compute_mse(manifest_path, weights)
        checked += 1
        if mse < best_mse:
            best_mse = mse
            best_weights = weights.copy()
            print(f"  New best: {weights}  MSE={mse:.6f}")

    print(f"\nChecked {checked} combinations.")
    return best_weights, best_mse


def _range(start: float, stop: float, step: float):
    v = start
    while v <= stop + 1e-9:
        yield v
        v = round(v + step, 10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="evaluation/ground_truth/manifest.json")
    ap.add_argument("--step", type=float, default=0.05, help="Grid step size (smaller = slower)")
    ap.add_argument("--output", default=None, help="JSON file to write results to")
    args = ap.parse_args()

    manifest = Path(args.dataset)
    if not manifest.exists():
        print(f"ERROR: {manifest} not found", file=sys.stderr)
        sys.exit(1)

    best_weights, best_mse = grid_search(manifest, step=args.step)
    baseline_mse = compute_mse(manifest, _CURRENT)

    print(f"\n{'=' * 55}")
    print(f"Best weights:    {best_weights}")
    print(f"Best MSE:        {best_mse:.6f}")
    print(f"Baseline MSE:    {baseline_mse:.6f}")
    print(f"Improvement:     {(baseline_mse - best_mse) / baseline_mse * 100:.1f}%")
    print(f"{'=' * 55}")
    print("\nUpdate app/pipelines/confidence.py with these constants:")
    for k, v in best_weights.items():
        print(f"  {k} = {v}")

    if args.output:
        Path(args.output).write_text(json.dumps({
            "best_weights": best_weights,
            "best_mse": best_mse,
            "baseline_mse": baseline_mse,
        }, indent=2))
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
