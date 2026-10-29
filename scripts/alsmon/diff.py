"""Diff two successful snapshots of the same monitoring query.

Leaving the query is reported as left_query_scope. It is never called cancelled.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from alsmon.constants import LEFT_SCOPE_NOTE, LEFT_SCOPE_NOTE_ZH
from alsmon.normalize import drug_biological_interventions


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "nctId": record.get("nctId"),
        "title": record.get("title"),
        "overallStatus": record.get("overallStatus"),
        "studyType": record.get("studyType"),
        "isExpandedAccess": record.get("isExpandedAccess"),
        "phases": list(record.get("phases") or []),
        "conditionScope": record.get("conditionScope"),
        "drugBiologicalInterventions": drug_biological_interventions(record),
        "hasResults": record.get("hasResults"),
        "lastUpdatePostDate": record.get("lastUpdatePostDate"),
    }


def _change(
    change_type: str,
    record_or_old: dict[str, Any],
    *,
    field: str,
    old: Any,
    new: Any,
    detected_at: str,
    note: str,
    note_zh: str,
) -> dict[str, Any]:
    nct_id = record_or_old.get("nctId")
    return {
        "type": change_type,
        "nctId": nct_id,
        "url": record_or_old.get("url") or f"https://clinicaltrials.gov/study/{nct_id}",
        "field": field,
        "old": old,
        "new": new,
        "firstSeenAt": record_or_old.get("firstSeenAt"),
        "detectedAt": detected_at,
        "note": note,
        "noteZh": note_zh,
    }


def diff_snapshots(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    detected_at: str,
    baseline_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Compare current against the previous successful snapshot only."""
    baseline_ids = baseline_ids or set()
    previous_map = {record["nctId"]: record for record in previous}
    current_map = {record["nctId"]: record for record in current}
    changes: list[dict[str, Any]] = []

    for nct_id in sorted(current_map):
        current_record = current_map[nct_id]
        if nct_id not in previous_map:
            in_registry = bool(current_record.get("_previouslyInRegistry"))
            if nct_id in baseline_ids or in_registry:
                changes.append(
                    _change(
                        "entered_query_scope",
                        current_record,
                        field="record",
                        old=None,
                        new=_summary(current_record),
                        detected_at=detected_at,
                        note=(
                            "This NCT entered the current monitoring result set. It was already "
                            "in the frozen baseline or an earlier registry entry, so it is not "
                            "reported as a brand-new registration."
                        ),
                        note_zh=(
                            "该 NCT 进入了本次监测结果。它已经在冻结基线或更早的登记里出现过，"
                            "因此不记为全新注册。"
                        ),
                    )
                )
            else:
                changes.append(
                    _change(
                        "new_registration",
                        current_record,
                        field="record",
                        old=None,
                        new=_summary(current_record),
                        detected_at=detected_at,
                        note=(
                            "First time this NCT appears in a successful snapshot of the "
                            "current monitoring query."
                        ),
                        note_zh="该 NCT 第一次出现在当前监测查询的成功快照中。",
                    )
                )
            continue

        old = previous_map[nct_id]
        if old.get("overallStatus") != current_record.get("overallStatus"):
            changes.append(
                _change(
                    "status_change",
                    current_record,
                    field="overallStatus",
                    old=old.get("overallStatus"),
                    new=current_record.get("overallStatus"),
                    detected_at=detected_at,
                    note="overallStatus changed. studyType is tracked separately.",
                    note_zh="原始注册状态 overallStatus 发生变化。研究类型 studyType 另行记录。",
                )
            )
        if list(old.get("phases") or []) != list(current_record.get("phases") or []):
            changes.append(
                _change(
                    "phase_change",
                    current_record,
                    field="phases",
                    old=list(old.get("phases") or []),
                    new=list(current_record.get("phases") or []),
                    detected_at=detected_at,
                    note="Phase list changed. A trial may list more than one phase.",
                    note_zh="分期列表发生变化。一条试验可以同时列出多个分期。",
                )
            )
        old_drugs = drug_biological_interventions(old)
        new_drugs = drug_biological_interventions(current_record)
        if old_drugs != new_drugs:
            changes.append(
                _change(
                    "intervention_change",
                    current_record,
                    field="drugBiologicalInterventions",
                    old=old_drugs,
                    new=new_drugs,
                    detected_at=detected_at,
                    note="Drug or biological intervention name or type changed.",
                    note_zh="药物或生物制剂干预的名称或类型发生变化。",
                )
            )
        if old.get("locationFingerprint") != current_record.get("locationFingerprint"):
            changes.append(
                _change(
                    "location_update",
                    current_record,
                    field="locations",
                    old={"count": len(old.get("locations") or []), "locations": old.get("locations") or []},
                    new={
                        "count": len(current_record.get("locations") or []),
                        "locations": current_record.get("locations") or [],
                    },
                    detected_at=detected_at,
                    note="Facility, city, country, or location status changed.",
                    note_zh="机构、城市、国家或地点状态发生变化。",
                )
            )
        if not old.get("hasResults") and current_record.get("hasResults"):
            changes.append(
                _change(
                    "results_published",
                    current_record,
                    field="hasResults",
                    old={
                        "hasResults": False,
                        "resultsFirstPostDate": old.get("resultsFirstPostDate"),
                    },
                    new={
                        "hasResults": True,
                        "resultsFirstPostDate": current_record.get("resultsFirstPostDate"),
                        "outcomeMeasures": current_record.get("outcomeMeasures") or [],
                    },
                    detected_at=detected_at,
                    note="Results became available on the public registration.",
                    note_zh="公开注册开始提供结果。",
                )
            )
        elif old.get("hasResults") and current_record.get("hasResults"):
            if old.get("resultsFingerprint") != current_record.get("resultsFingerprint"):
                changes.append(
                    _change(
                        "results_field_change",
                        current_record,
                        field="outcomeMeasures",
                        old={
                            "resultsFirstPostDate": old.get("resultsFirstPostDate"),
                            "resultsFirstSubmitDate": old.get("resultsFirstSubmitDate"),
                            "outcomeMeasures": old.get("outcomeMeasures") or [],
                        },
                        new={
                            "resultsFirstPostDate": current_record.get("resultsFirstPostDate"),
                            "resultsFirstSubmitDate": current_record.get("resultsFirstSubmitDate"),
                            "outcomeMeasures": current_record.get("outcomeMeasures") or [],
                        },
                        detected_at=detected_at,
                        note="Posted results fields changed after results were already present.",
                        note_zh="结果已经发布之后，结果字段又发生了变化。",
                    )
                )
        if (old.get("title") or "") != (current_record.get("title") or ""):
            changes.append(
                _change(
                    "title_change",
                    current_record,
                    field="title",
                    old=old.get("title"),
                    new=current_record.get("title"),
                    detected_at=detected_at,
                    note="Public brief title changed.",
                    note_zh="公开简题发生变化。",
                )
            )
        if (old.get("sponsor") or "") != (current_record.get("sponsor") or ""):
            changes.append(
                _change(
                    "sponsor_change",
                    current_record,
                    field="sponsor",
                    old=old.get("sponsor"),
                    new=current_record.get("sponsor"),
                    detected_at=detected_at,
                    note="Lead sponsor name changed.",
                    note_zh="主要申办方名称发生变化。",
                )
            )
        if list(old.get("conditions") or []) != list(current_record.get("conditions") or []) or old.get(
            "conditionScope"
        ) != current_record.get("conditionScope"):
            changes.append(
                _change(
                    "condition_change",
                    current_record,
                    field="conditions",
                    old={
                        "conditions": list(old.get("conditions") or []),
                        "conditionScope": old.get("conditionScope"),
                    },
                    new={
                        "conditions": list(current_record.get("conditions") or []),
                        "conditionScope": current_record.get("conditionScope"),
                    },
                    detected_at=detected_at,
                    note=(
                        "Listed conditions changed. This can move a study between the strict ALS "
                        "subset and the broader motor-neuron-disease search scope."
                    ),
                    note_zh="登记的疾病条件变了。研究可能因此在「严格 ALS」和「更广的运动神经元病检索」之间变动。",
                )
            )
        if old.get("studyType") != current_record.get("studyType"):
            changes.append(
                _change(
                    "study_type_change",
                    current_record,
                    field="studyType",
                    old=old.get("studyType"),
                    new=current_record.get("studyType"),
                    detected_at=detected_at,
                    note="studyType changed. Expanded access follows this field, not overallStatus.",
                    note_zh="研究类型 studyType 发生变化。扩展使用以该字段为准，不以 overallStatus 代替。",
                )
            )

    for nct_id in sorted(previous_map):
        if nct_id in current_map:
            continue
        old = previous_map[nct_id]
        changes.append(
            _change(
                "left_query_scope",
                old,
                field="queryMembership",
                old=_summary(old),
                new=None,
                detected_at=detected_at,
                note=LEFT_SCOPE_NOTE,
                note_zh=LEFT_SCOPE_NOTE_ZH,
            )
        )
    return changes


def summarize_changes(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(change["type"] for change in changes)
    return dict(sorted(counts.items()))


def strip_internal_flags(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(record)
    cleaned.pop("_previouslyInRegistry", None)
    return cleaned
