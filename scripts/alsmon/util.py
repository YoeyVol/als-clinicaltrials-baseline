"""JSON canonicalization, hashing, and small accessors."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

NCT_RE = re.compile(r"^NCT\d{8}$")
FULL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PARTIAL_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def canonical_json(value: Any) -> str:
    """Stable JSON used for checksums. Key order does not matter."""
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def dig(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def as_date(value: Any) -> str | None:
    """Return a date string from an API date or `{date: ...}` struct."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("date")
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def is_full_date(value: str | None) -> bool:
    return value is None or bool(FULL_DATE_RE.match(value))


def is_partial_date(value: str | None) -> bool:
    return value is None or bool(PARTIAL_DATE_RE.match(value))


def nct_url(nct_id: str) -> str:
    return f"https://clinicaltrials.gov/study/{nct_id}"
