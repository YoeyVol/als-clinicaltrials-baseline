"""Run one sync. Failures and anomalies leave the last good snapshot untouched."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alsmon.api import (
    ApiError,
    PageFetch,
    PaginationError,
    fetch_all_pages,
    fetch_broad_count,
    make_live_page_fetch,
)
from alsmon.constants import (
    API_URL,
    BASELINE_ID,
    BASELINE_TIMESTAMP,
    HISTORICAL_BROAD_COUNT,
    HISTORICAL_EMBEDDED_COUNT,
    MONITORING_CONDITION,
    MONITORING_FILTER,
    PAGE_SIZE,
    SCHEMA_VERSION,
    SCOPE_REVIEW_NOTE,
    SCOPE_REVIEW_NOTE_ZH,
    SCRIPT_VERSION,
    SOURCE_NAME,
    STUDY_FIELDS,
)
from alsmon.diff import diff_snapshots, strip_internal_flags, summarize_changes
from alsmon.metrics import compute_metrics, max_last_update
from alsmon.normalize import normalize_study
from alsmon.store import (
    RepoPaths,
    StoreError,
    atomic_write_many,
    load_baseline_ids,
    load_json_object,
    load_studies_document,
)
from alsmon.util import pretty_json, sha256_json
from alsmon.validate import detect_anomalies, validate_records


@dataclass
class SyncResult:
    status: str
    changed: bool
    exit_code: int
    message: str
    anomalies: list[str] = field(default_factory=list)
    report: dict[str, Any] | None = None
    record_count: int | None = None


def _now_iso(now: datetime | None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_id(detected_at: str) -> str:
    return detected_at.replace("-", "").replace(":", "")


def _scope_review(current_ids: set[str], baseline_ids: set[str]) -> dict[str, Any]:
    only_current = sorted(current_ids - baseline_ids)
    only_baseline = sorted(baseline_ids - current_ids)
    both = sorted(current_ids & baseline_ids)
    return {
        "baselineId": BASELINE_ID,
        "baselineRecordCount": len(baseline_ids),
        "currentRecordCount": len(current_ids),
        "intersectionCount": len(both),
        "onlyInBaselineCount": len(only_baseline),
        "onlyInCurrentCount": len(only_current),
        "onlyInBaseline": only_baseline,
        "onlyInCurrent": only_current,
        "historicalBroadConditionSearchCount": HISTORICAL_BROAD_COUNT,
        "historicalEmbeddedCount": HISTORICAL_EMBEDDED_COUNT,
        "note": SCOPE_REVIEW_NOTE,
        "noteZh": SCOPE_REVIEW_NOTE_ZH,
        "notNewTrials": True,
        "notCancellations": True,
    }


def _assign_first_seen(
    records: list[dict[str, Any]],
    *,
    previous_map: dict[str, dict[str, Any]],
    registry: dict[str, str],
    baseline_ids: set[str],
    detected_at: str,
) -> dict[str, str]:
    updated = dict(registry)
    for record in records:
        nct_id = record["nctId"]
        record["_previouslyInRegistry"] = nct_id in registry or nct_id in previous_map
        if nct_id in registry:
            record["firstSeenAt"] = registry[nct_id]
        elif nct_id in previous_map and previous_map[nct_id].get("firstSeenAt"):
            record["firstSeenAt"] = previous_map[nct_id]["firstSeenAt"]
        elif nct_id in baseline_ids:
            record["firstSeenAt"] = BASELINE_TIMESTAMP
        else:
            record["firstSeenAt"] = detected_at
        updated[nct_id] = record["firstSeenAt"]
    return updated


def _broad_block(total: int | None, warning: str | None) -> dict[str, Any]:
    return {
        "query": {"query.cond": MONITORING_CONDITION},
        "totalCount": total,
        "meaning": (
            "Background size of query.cond=ALS before the drug, biological, or "
            "expanded-access filter. This is not the frozen 2026-10-28 count of "
            f"{HISTORICAL_BROAD_COUNT}."
        ),
        "warning": warning,
    }


def run_sync(
    repo_root: Path | str,
    *,
    page_fetch: PageFetch | None = None,
    now: datetime | None = None,
    write: bool = True,
    sleeper: Any = None,
    page_delay: float | None = None,
) -> SyncResult:
    """Fetch, validate, diff, and write only a successful non-anomalous snapshot."""
    root = Path(repo_root)
    paths = RepoPaths.from_root(root)
    detected_at = _now_iso(now)
    live = page_fetch is None
    if page_fetch is None:
        page_fetch = make_live_page_fetch(sleeper=sleeper or __import__("time").sleep)
    if sleeper is None:
        sleeper = (lambda _seconds: None) if not live else __import__("time").sleep
    if page_delay is None:
        page_delay = 0.25 if live else 0.0

    try:
        previous_doc = load_studies_document(paths.studies)
        previous_meta = load_json_object(paths.meta) if paths.meta.exists() else {}
        registry_doc = load_json_object(paths.registry) if paths.registry.exists() else {}
        baseline_id_list = load_baseline_ids(paths.baseline)
    except StoreError as exc:
        return SyncResult("error", False, 1, str(exc))

    previous_records = list(previous_doc.get("records") or []) if previous_doc else []
    previous_map = {record["nctId"]: record for record in previous_records if "nctId" in record}
    registry = {key: value for key, value in registry_doc.items() if isinstance(key, str)}
    baseline_ids = set(baseline_id_list)

    try:
        fetched = fetch_all_pages(page_fetch, sleeper=sleeper, page_delay=page_delay)
        broad_total = fetch_broad_count(page_fetch)
    except (ApiError, PaginationError) as exc:
        return SyncResult(
            "error",
            False,
            1,
            f"API or pagination failure; last good snapshot was not modified. {exc}",
        )

    broad_warning = None
    if broad_total is None:
        broad_warning = "Broad condition-search count was unavailable. The monitoring set was still checked."

    normalize_errors: list[str] = []
    records: list[dict[str, Any]] = []
    for raw in fetched["studies"]:
        record, errors = normalize_study(raw)
        normalize_errors.extend(errors)
        if record is not None and not errors:
            records.append(record)
        elif record is not None and errors:
            records.append(record)

    records.sort(key=lambda record: record["nctId"])
    validation_errors = list(normalize_errors)
    validation_errors.extend(validate_records(records))
    anomalies = detect_anomalies(
        records=records,
        previous_count=len(previous_records) if previous_doc else None,
        validation_errors=validation_errors,
        total_count=fetched["totalCount"],
    )
    if anomalies:
        detail = "; ".join(validation_errors[:8])
        return SyncResult(
            "anomaly",
            False,
            2,
            "Anomalous snapshot was not written. Last good data was preserved. "
            f"Anomalies: {', '.join(anomalies)}. {detail}".strip(),
            anomalies=anomalies,
            record_count=len(records),
        )

    updated_registry = _assign_first_seen(
        records,
        previous_map=previous_map,
        registry=registry,
        baseline_ids=baseline_ids,
        detected_at=detected_at,
    )
    current_ids = {record["nctId"] for record in records}
    scope = _scope_review(current_ids, baseline_ids)
    changes: list[dict[str, Any]] = []
    kind = "diff"
    if previous_doc is None:
        kind = "initial_snapshot"
    else:
        changes = diff_snapshots(
            previous_records,
            records,
            detected_at=detected_at,
            baseline_ids=baseline_ids,
        )

    previous_broad = None
    if isinstance(previous_meta.get("broadConditionSearch"), dict):
        previous_broad = previous_meta["broadConditionSearch"].get("totalCount")
    if previous_doc is not None and broad_total is not None and previous_broad != broad_total:
        changes.append(
            {
                "type": "context_count_change",
                "nctId": None,
                "url": "https://clinicaltrials.gov/search?cond=ALS",
                "field": "broadConditionSearch.totalCount",
                "old": previous_broad,
                "new": broad_total,
                "firstSeenAt": None,
                "detectedAt": detected_at,
                "note": (
                    "Background condition-search total changed. This is not a new trial "
                    "and not a cancellation inside the monitoring set."
                ),
                "noteZh": "条件检索的背景总数变了。这不是监测集里的新增试验，也不是取消。",
            }
        )

    stored_records = [strip_internal_flags(record) for record in records]
    checksum = sha256_json(stored_records)
    previous_checksum = previous_meta.get("checksumSha256")
    # A commit is warranted only for a first snapshot or a tracked change.
    # A lone lastUpdatePostDate bump is not a tracked change; see README.
    material_changes = kind == "initial_snapshot" or bool(changes)
    if not material_changes:
        return SyncResult(
            "no_change",
            False,
            0,
            f"No material change in {len(stored_records)} records. Last good snapshot was left as-is.",
            record_count=len(stored_records),
        )

    metrics = compute_metrics(stored_records)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "id": _report_id(detected_at),
        "kind": kind,
        "detectedAt": detected_at,
        "scriptVersion": SCRIPT_VERSION,
        "source": SOURCE_NAME,
        "sourceEndpoint": API_URL,
        "query": {
            "query.cond": MONITORING_CONDITION,
            "filter.advanced": MONITORING_FILTER,
            "pageSize": PAGE_SIZE,
            "fields": STUDY_FIELDS,
        },
        "previousSnapshotId": previous_checksum,
        "currentSnapshotId": checksum,
        "previousRecordCount": len(previous_records) if previous_doc else None,
        "currentRecordCount": len(stored_records),
        "summary": summarize_changes(changes),
        "changes": changes,
        "scopeReview": {
            "baselineId": scope["baselineId"],
            "intersectionCount": scope["intersectionCount"],
            "onlyInBaselineCount": scope["onlyInBaselineCount"],
            "onlyInCurrentCount": scope["onlyInCurrentCount"],
            "note": scope["note"],
            "noteZh": scope["noteZh"],
            "notNewTrials": True,
            "notCancellations": True,
        },
    }
    meta = {
        "schemaVersion": SCHEMA_VERSION,
        "scriptVersion": SCRIPT_VERSION,
        "runStatus": "success",
        "source": SOURCE_NAME,
        "sourceEndpoint": API_URL,
        "sourceUpdatedAt": max_last_update(stored_records),
        "sourceUpdatedAtMeaning": (
            "Maximum lastUpdatePostDate among studies in this snapshot. "
            "This is the newest study-level post date in the result, not a separate "
            "ClinicalTrials.gov database clock."
        ),
        "syncedAt": detected_at,
        "recordCount": len(stored_records),
        "checksumSha256": checksum,
        "snapshotId": checksum,
        "query": report["query"],
        "pagesFetched": fetched["pagesFetched"],
        "totalCountReported": fetched["totalCount"],
        "broadConditionSearch": _broad_block(broad_total, broad_warning),
        "metrics": metrics,
        "monitoringQueryDiffersFromFrozenBaseline": True,
        "frozenBaseline": {
            "id": BASELINE_ID,
            "timestamp": BASELINE_TIMESTAMP,
            "embeddedRecordCount": HISTORICAL_EMBEDDED_COUNT,
            "broadConditionSearchCount": HISTORICAL_BROAD_COUNT,
            "note": SCOPE_REVIEW_NOTE,
            "noteZh": SCOPE_REVIEW_NOTE_ZH,
        },
        "warnings": [broad_warning] if broad_warning else [],
    }
    studies_doc = {
        "schemaVersion": SCHEMA_VERSION,
        "scriptVersion": SCRIPT_VERSION,
        "records": stored_records,
    }
    # Keep NCT ids that have left the query so a later return is not called new.
    merged_registry = dict(registry)
    merged_registry.update(updated_registry)

    index = load_json_object(paths.changes_index) if paths.changes_index.exists() else {"reports": []}
    reports = list(index.get("reports") or [])
    report_name = f"{report['id']}.json"
    reports.append(
        {
            "id": report["id"],
            "path": f"data/changes/{report_name}",
            "detectedAt": detected_at,
            "kind": kind,
            "changeCount": len(changes),
            "summary": report["summary"],
        }
    )
    index_doc = {"schemaVersion": SCHEMA_VERSION, "reports": reports}

    message = (
        f"{kind}: {len(stored_records)} records, {len(changes)} change entries. "
        f"Scope versus {BASELINE_ID}: intersection {scope['intersectionCount']}, "
        f"only in baseline {scope['onlyInBaselineCount']}, "
        f"only in current query {scope['onlyInCurrentCount']} "
        "(scope review, not new trials or cancellations)."
    )
    if not write:
        return SyncResult("success", True, 0, "Dry run. " + message, report=report, record_count=len(stored_records))

    files = {
        paths.studies: pretty_json(studies_doc),
        paths.meta: pretty_json(meta),
        paths.scope: pretty_json(scope),
        paths.changes_dir / report_name: pretty_json(report),
        paths.changes_latest: pretty_json(report),
        paths.changes_index: pretty_json(index_doc),
        paths.registry: pretty_json(merged_registry),
    }
    try:
        atomic_write_many(root, files)
    except StoreError as exc:
        return SyncResult("error", False, 1, str(exc), report=report, record_count=len(stored_records))
    return SyncResult("success", True, 0, message, report=report, record_count=len(stored_records))


def emit_github_output(result: SyncResult) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    summary = " ".join(result.message.split())[:400]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if result.changed else 'false'}\n")
        handle.write(f"status={result.status}\n")
        handle.write(f"summary={summary}\n")


def check_repository(repo_root: Path | str) -> SyncResult:
    """Offline integrity check. Does not contact the network or write data."""
    root = Path(repo_root)
    paths = RepoPaths.from_root(root)
    problems: list[str] = []
    try:
        from alsmon.baseline import verify_baseline

        verify_baseline(paths.baseline, paths.baseline_meta)
    except Exception as exc:  # noqa: BLE001 - reported as a check failure
        problems.append(f"baseline: {exc}")
    if not paths.studies.exists():
        problems.append("latest snapshot is missing")
    else:
        try:
            document = load_studies_document(paths.studies)
        except StoreError as exc:
            problems.append(str(exc))
            document = None
        if document is not None:
            records = document["records"]
            errors = validate_records(records)
            problems.extend(errors[:12])
            meta = load_json_object(paths.meta) if paths.meta.exists() else {}
            checksum = sha256_json(records)
            if meta.get("checksumSha256") and meta.get("checksumSha256") != checksum:
                problems.append("latest checksum does not match studies.json")
            if meta.get("runStatus") != "success":
                problems.append("latest meta runStatus is not success")
            metrics = compute_metrics(records)
            if metrics["statusCountSum"] != metrics["recordCount"]:
                problems.append("status counts do not sum to the record count")
    if problems:
        return SyncResult("error", False, 1, "Check failed. " + " | ".join(problems))
    return SyncResult("success", False, 0, "Offline check passed. Frozen baseline and latest snapshot are intact.")
