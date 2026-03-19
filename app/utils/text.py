import re
from typing import Any


_OCR_SUBS = [
    (r"\b0(?=[A-Z]{2,})", "O"),
    (r"(?<=[A-Z]{2})0(?=[A-Z\-])", "O"),
    (r"\bINV-(\d)O(\d{2})", r"INV-\g<1>0\g<2>"),
    (r"\bl(?=[A-Z][A-Z0-9\-])", "I"),
    (r"(?<=[A-Z])1(?=[A-Z]{2,})", "I"),
    (r"\blnv", "Inv"),
    (r"\bBi11\b", "Bill"),
    (r"\bT0tal\b", "Total"),
    (r"\bStat\s+ement\b", "Statement"),
    (r"\bAcc0unt\b", "Account"),
    (r"\bP3ri0d\b", "Period"),
    (r"\b0pening\b", "Opening"),
    (r"\bC1osing\b", "Closing"),
    (r"\bAvai1able\b", "Available"),
    (r"\bSa1ary\b", "Salary"),
    (r"\bDeb1t\b", "Debit"),
    (r"\bCred1t\b", "Credit"),
    (r"\bSubt0tal\b", "Subtotal"),
    (r"\bFr0m\b", "From"),
    (r"(?<=[A-Z]{2,})0(?=\d)", "O"),
]
_OCR_COMPILED = [(re.compile(pattern), replacement) for pattern, replacement in _OCR_SUBS]


def normalize_ocr_artifacts(text: str) -> str:
    """Fix common OCR character substitutions before field extraction."""
    for pattern, replacement in _OCR_COMPILED:
        text = pattern.sub(replacement, text)
    return text


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d\.\-]", "", raw)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def regex_search(pattern: str, text: str, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return normalize_whitespace(value) if value else None


def find_snippet(text: str, needle: str | None, window: int = 100) -> str | None:
    if not needle:
        return None
    lowered = text.lower()
    idx = lowered.find(needle.lower())
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(text), idx + len(needle) + window)
    return normalize_whitespace(text[start:end])


def deep_set(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cursor = payload
    for key in parts[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[parts[-1]] = value
