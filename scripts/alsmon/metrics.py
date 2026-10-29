"""Metrics derived from records. Nothing here is a hardcoded trial count."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _status(record: dict[str, Any]) -> str:
    if "overallStatus" in record:
        return str(record.get("overallStatus") or "")
    return str(record.get("status") or "")


def _phases(record: dict[str, Any]) -> list[str]:
    phases = record.get("phases") or []
    if not isinstance(phases, list):
        return []
    return [phase for phase in phases if isinstance(phase, str) and phase]


def compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    phase_counts: Counter[str] = Counter()
    multi_phase = 0
    expanded = 0
    strict = 0
    broader = 0
    unspecified = 0
    other = 0
    for record in records:
        status_counts[_status(record)] += 1
        phases = _phases(record)
        if len(phases) > 1:
            multi_phase += 1
        if not phases:
            phase_counts["UNSPECIFIED"] += 1
        else:
            for phase in phases:
                phase_counts[phase] += 1
        if record.get("isExpandedAccess") is True:
            expanded += 1
        scope = record.get("conditionScope")
        if scope == "strict_als":
            strict += 1
        elif scope == "broader_mnd":
            broader += 1
        elif scope == "unspecified":
            unspecified += 1
        elif scope == "other":
            other += 1
    phase_sum = sum(phase_counts.values())
    return {
        "recordCount": len(records),
        "statusCounts": dict(sorted(status_counts.items())),
        "statusCountSum": sum(status_counts.values()),
        "phaseCounts": dict(sorted(phase_counts.items())),
        "phaseCountSum": phase_sum,
        "codedPhaseAssignments": phase_sum - phase_counts.get("UNSPECIFIED", 0),
        "phaseCountsOverlap": phase_sum > len(records),
        "multiPhaseCount": multi_phase,
        "expandedAccessCount": expanded,
        "strictAlsCount": strict,
        "broaderMndCount": broader,
        "unspecifiedConditionCount": unspecified,
        "otherConditionCount": other,
        "recruitingOnlyCount": status_counts.get("RECRUITING", 0),
        "notYetRecruitingCount": status_counts.get("NOT_YET_RECRUITING", 0),
        "enrollingByInvitationCount": status_counts.get("ENROLLING_BY_INVITATION", 0),
        "activeNotRecruitingCount": status_counts.get("ACTIVE_NOT_RECRUITING", 0),
    }


def legacy_page_buckets(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Reproduce the old static-page buckets so the口径 can be explained.

    The old card added RECRUITING, NOT_YET_RECRUITING, ENROLLING_BY_INVITATION,
    and AVAILABLE, then labeled the sum 「招募中类」. That sum is not a count of
    recruiting trials. AVAILABLE is an expanded-access status.
    """
    counts: Counter[str] = Counter(_status(record) for record in records)
    merged = (
        counts["RECRUITING"]
        + counts["NOT_YET_RECRUITING"]
        + counts["ENROLLING_BY_INVITATION"]
        + counts["AVAILABLE"]
    )
    active = counts["ACTIVE_NOT_RECRUITING"]
    return {
        "recruiting": counts["RECRUITING"],
        "notYetRecruiting": counts["NOT_YET_RECRUITING"],
        "enrollingByInvitation": counts["ENROLLING_BY_INVITATION"],
        "available": counts["AVAILABLE"],
        "activeNotRecruiting": active,
        "mergedRecruitingLike": merged,
        "ongoingIncludingNotRecruiting": merged + active,
        "warning": (
            "mergedRecruitingLike adds RECRUITING, NOT_YET_RECRUITING, "
            "ENROLLING_BY_INVITATION, and AVAILABLE. It is not a count of "
            "recruiting trials. AVAILABLE is an expanded-access status."
        ),
        "warningZh": (
            "mergedRecruitingLike 把招募中、尚未招募、邀请入组和扩展使用状态 AVAILABLE 加在一起。"
            "它不是正在招募的试验数。AVAILABLE 属于扩展使用，不应算作普通招募中。"
        ),
    }


def max_last_update(records: list[dict[str, Any]]) -> str | None:
    dates = [
        record.get("lastUpdatePostDate")
        for record in records
        if isinstance(record.get("lastUpdatePostDate"), str)
    ]
    return max(dates) if dates else None
