"""Record and snapshot checks. Anomalies must not replace the last good snapshot."""

from __future__ import annotations

from typing import Any

from alsmon.constants import MAX_MISSING_UPDATE_DATE_FRACTION, SHARP_DROP_MIN_PREVIOUS, SHARP_DROP_RATIO
from alsmon.util import NCT_RE, is_full_date, is_partial_date


def validate_records(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    missing_update = 0
    for index, record in enumerate(records):
        nct_id = record.get("nctId")
        label = nct_id if isinstance(nct_id, str) else f"row {index}"
        if not isinstance(nct_id, str) or not NCT_RE.match(nct_id):
            errors.append(f"{label}: nctId is missing or not NCT########")
        else:
            seen[nct_id] = seen.get(nct_id, 0) + 1
        if not str(record.get("title") or "").strip():
            errors.append(f"{label}: missing title")
        if not str(record.get("overallStatus") or "").strip():
            errors.append(f"{label}: missing overallStatus")
        if not str(record.get("studyType") or "").strip():
            errors.append(f"{label}: missing studyType")
        if not isinstance(record.get("phases"), list):
            errors.append(f"{label}: phases is not a list")
        if record.get("isExpandedAccess") is not (record.get("studyType") == "EXPANDED_ACCESS"):
            errors.append(f"{label}: isExpandedAccess does not match studyType")
        if not str(record.get("url") or "").startswith("https://clinicaltrials.gov/study/"):
            errors.append(f"{label}: official study URL is missing")
        for field in (
            "lastUpdatePostDate",
            "studyFirstPostDate",
            "lastUpdateSubmitDate",
            "resultsFirstPostDate",
            "resultsFirstSubmitDate",
        ):
            value = record.get(field)
            if value is not None and not is_full_date(value if isinstance(value, str) else "bad"):
                errors.append(f"{label}: {field} is not YYYY-MM-DD")
        verified = record.get("statusVerifiedDate")
        if verified is not None and not is_partial_date(verified if isinstance(verified, str) else "bad"):
            errors.append(f"{label}: statusVerifiedDate is not a date")
        if not record.get("lastUpdatePostDate"):
            missing_update += 1
    for nct_id, count in sorted(seen.items()):
        if count > 1:
            errors.append(f"{nct_id}: duplicate NCT ({count})")
    if records:
        fraction = missing_update / len(records)
        if fraction > MAX_MISSING_UPDATE_DATE_FRACTION:
            errors.append(
                f"time fields incomplete: {missing_update}/{len(records)} rows lack lastUpdatePostDate"
            )
    return errors


def detect_anomalies(
    *,
    records: list[dict[str, Any]],
    previous_count: int | None,
    validation_errors: list[str],
    total_count: int,
) -> list[str]:
    """Name anomalous runs. Empty data and sharp drops are not written over last-good."""
    anomalies: list[str] = []
    if validation_errors:
        anomalies.append("schema_invalid")
    if total_count == 0 or len(records) == 0:
        anomalies.append("empty_dataset")
    if (
        previous_count is not None
        and previous_count >= SHARP_DROP_MIN_PREVIOUS
        and len(records) < previous_count * SHARP_DROP_RATIO
    ):
        anomalies.append("sharp_count_drop")
    return anomalies
