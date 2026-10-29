"""Extract and verify the frozen 2026-10-28 baseline.

The baseline file is the exact record array that used to live in
``const DATA = [...]`` inside index.html. Sync never rewrites it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from alsmon.constants import (
    BASELINE_ID,
    BASELINE_TIMESTAMP,
    HISTORICAL_BROAD_COUNT,
    HISTORICAL_EMBEDDED_COUNT,
    SCRIPT_VERSION,
)
from alsmon.metrics import legacy_page_buckets
from alsmon.util import sha256_json

# SHA-256 of the canonical (sorted-key) JSON array. Filled after extraction
# and locked by tests. verify_baseline also checks the meta checksum, the
# historical counts, and the derived口径 below.
EXPECTED_BASELINE_SHA256 = "34712b2177c88c14ae88c89f08478116e6cd0bd3c64b8f9f967d92996dc273a3"

SOURCE_COMMIT = "ac12ac1fbacf51c532782fc9766aaf9bd0f1725f"
EXPECTED_STATUS_COUNTS = {
    "COMPLETED": 254,
    "TERMINATED": 50,
    "RECRUITING": 44,
    "UNKNOWN": 42,
    "NOT_YET_RECRUITING": 29,
    "ACTIVE_NOT_RECRUITING": 28,
    "WITHDRAWN": 17,
    "NO_LONGER_AVAILABLE": 7,
    "ENROLLING_BY_INVITATION": 5,
    "SUSPENDED": 3,
    "AVAILABLE": 3,
    "TEMPORARILY_NOT_AVAILABLE": 2,
    "APPROVED_FOR_MARKETING": 2,
}
EXPECTED_PHASE_COUNTS = {
    "PHASE2": 267,
    "PHASE1": 166,
    "PHASE3": 92,
    "EARLY_PHASE1": 18,
    "NA": 13,
    "PHASE4": 7,
}
EXPECTED_CODED_PHASE_ASSIGNMENTS = 563
EXPECTED_EMPTY_PHASES = 24
EXPECTED_LEGACY_MERGED = 81
EXPECTED_LEGACY_ONGOING = 109
KENNEDY_NCT = "NCT00004771"


class BaselineError(Exception):
    pass


def extract_data_array(html: str) -> list[dict[str, Any]]:
    marker = "const DATA = "
    start = html.find(marker)
    if start < 0:
        raise BaselineError("index.html has no const DATA array to extract")
    payload, _end = json.JSONDecoder().raw_decode(html, start + len(marker))
    if not isinstance(payload, list):
        raise BaselineError("const DATA was not a JSON array")
    return payload


def page_card_values(html: str) -> list[int]:
    return [int(value) for value in re.findall(r'<div class="val">(\d+)</div>', html)]


def _phase_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for phase in record.get("phases") or []:
            counts[phase] = counts.get(phase, 0) + 1
    return counts


def _status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = record.get("status") or ""
        counts[status] = counts.get(status, 0) + 1
    return counts


def assert_historical_shape(records: list[dict[str, Any]]) -> dict[str, Any]:
    if len(records) != HISTORICAL_EMBEDDED_COUNT:
        raise BaselineError(f"expected {HISTORICAL_EMBEDDED_COUNT} records, found {len(records)}")
    ids = [record.get("nct") for record in records]
    if any(not isinstance(nct, str) for nct in ids):
        raise BaselineError("a baseline record is missing nct")
    if len(set(ids)) != len(ids):
        raise BaselineError("baseline NCT ids are not unique")
    status_counts = _status_counts(records)
    if status_counts != EXPECTED_STATUS_COUNTS:
        raise BaselineError(f"status counts changed: {status_counts}")
    phase_counts = _phase_counts(records)
    if phase_counts != EXPECTED_PHASE_COUNTS:
        raise BaselineError(f"phase counts changed: {phase_counts}")
    empty_phases = sum(1 for record in records if not record.get("phases"))
    coded = sum(len(record.get("phases") or []) for record in records)
    if empty_phases != EXPECTED_EMPTY_PHASES or coded != EXPECTED_CODED_PHASE_ASSIGNMENTS:
        raise BaselineError(f"phase口径 changed: coded={coded} empty={empty_phases}")
    if coded <= len(records):
        raise BaselineError("coded phase assignments should overlap and exceed the record count")
    legacy = legacy_page_buckets(records)
    if legacy["mergedRecruitingLike"] != EXPECTED_LEGACY_MERGED:
        raise BaselineError("legacy merged recruiting-like bucket changed")
    if legacy["ongoingIncludingNotRecruiting"] != EXPECTED_LEGACY_ONGOING:
        raise BaselineError("legacy ongoing bucket changed")
    if legacy["recruiting"] != 44:
        raise BaselineError("RECRUITING count changed")
    kennedy = next((record for record in records if record.get("nct") == KENNEDY_NCT), None)
    if kennedy is None or "Kennedy" not in kennedy.get("title", ""):
        raise BaselineError(f"{KENNEDY_NCT} Kennedy's Disease record is missing")
    return {
        "statusCounts": status_counts,
        "phaseCounts": phase_counts,
        "emptyPhaseRecords": empty_phases,
        "codedPhaseAssignments": coded,
        "legacyPageBuckets": legacy,
        "multiPhaseRecords": sum(1 for record in records if len(record.get("phases") or []) > 1),
    }


def build_metadata(records: list[dict[str, Any]], *, source_html_cards: list[int]) -> dict[str, Any]:
    derived = assert_historical_shape(records)
    if source_html_cards[:2] != [HISTORICAL_BROAD_COUNT, HISTORICAL_EMBEDDED_COUNT]:
        raise BaselineError(f"index.html card values are not the frozen pair: {source_html_cards[:4]}")
    return {
        "id": BASELINE_ID,
        "frozen": True,
        "immutable": True,
        "doNotRewrite": True,
        "scriptVersion": SCRIPT_VERSION,
        "extractor": "baseline-extract-1.1.0",
        "source": "const DATA array embedded in index.html",
        "sourcePage": "index.html",
        "sourceCommit": SOURCE_COMMIT,
        "sourceUrl": "https://clinicaltrials.gov/",
        "snapshotTimestamp": BASELINE_TIMESTAMP,
        "snapshotTimestampMeaning": (
            "Export time printed on the original static page: 2026-10-28 23:59 PDT. "
            "The page did not store an API query timestamp separate from that label."
        ),
        "recordCount": len(records),
        "checksumSha256": sha256_json(records),
        "checksumMeaning": "SHA-256 of canonical JSON (sorted keys, indent 2) for the record array.",
        "scope": {
            "description": (
                "Historical static export. The page described a broad ALS/MND-related "
                "condition search and embedded the drug, biological, and expanded-access "
                "candidates from that export. The exact ClinicalTrials.gov API query string "
                "was not stored on the page."
            ),
            "descriptionZh": (
                "历史静态导出。页面记录了广义 ALS/运动神经元病条件检索规模，并内嵌其中的"
                "药物、生物制剂和扩展使用候选。原始页面没有保存精确的 API 查询字符串。"
            ),
            "broadConditionSearchCount": HISTORICAL_BROAD_COUNT,
            "broadConditionSearchCountSource": "index.html overview card, not recomputed",
            "embeddedRecordCount": HISTORICAL_EMBEDDED_COUNT,
            "embeddedRecordCountSource": "length of const DATA",
            "conditionSearchMayBeBroaderThanStrictAls": True,
            "exampleBeyondStrictAls": {
                "nct": KENNEDY_NCT,
                "title": next(record["title"] for record in records if record["nct"] == KENNEDY_NCT),
                "reason": "Title names Kennedy's Disease or other motor neuron disease and does not name ALS.",
            },
        },
        "derivedFromRecords": derived,
        "notes": [
            "These counts are a frozen historical baseline, not current truth.",
            "Do not replace this file with a later API pull.",
            "1097 is the broad background count printed in 2026; it is not the number of rows in this file.",
            "486 is the number of rows in this file.",
            "Phase bars over-count trials that list more than one phase.",
            "The old 「招募中类」 figure merged several statuses and must not be read as N recruiting trials.",
        ],
    }


def verify_baseline(baseline_path: Path, meta_path: Path) -> dict[str, Any]:
    if not baseline_path.exists() or not meta_path.exists():
        raise BaselineError("frozen baseline files are missing")
    records = json.loads(baseline_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise BaselineError("baseline file must stay a JSON array")
    if meta.get("frozen") is not True or meta.get("doNotRewrite") is not True:
        raise BaselineError("baseline metadata is no longer marked frozen")
    if meta.get("recordCount") != HISTORICAL_EMBEDDED_COUNT:
        raise BaselineError("baseline metadata recordCount was rewritten")
    scope = meta.get("scope") or {}
    if scope.get("broadConditionSearchCount") != HISTORICAL_BROAD_COUNT:
        raise BaselineError("historical broad count was rewritten")
    if scope.get("embeddedRecordCount") != HISTORICAL_EMBEDDED_COUNT:
        raise BaselineError("historical embedded count was rewritten")
    checksum = sha256_json(records)
    if meta.get("checksumSha256") != checksum:
        raise BaselineError("baseline checksum does not match the records")
    if EXPECTED_BASELINE_SHA256 and checksum != EXPECTED_BASELINE_SHA256:
        raise BaselineError("baseline checksum does not match the locked historical hash")
    assert_historical_shape(records)
    meta["checksumSha256"] = checksum
    return meta


def write_baseline(repo_root: Path, html: str, *, force: bool = False) -> Path:
    records = extract_data_array(html)
    cards = page_card_values(html)
    meta = build_metadata(records, source_html_cards=cards)
    baseline_dir = repo_root / "data" / "baselines"
    baseline_path = baseline_dir / f"{BASELINE_ID}.json"
    meta_path = baseline_dir / f"{BASELINE_ID}.meta.json"
    if baseline_path.exists() and not force:
        verify_baseline(baseline_path, meta_path)
        return baseline_path
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    verify_baseline(baseline_path, meta_path)
    return baseline_path
