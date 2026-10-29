"""Normalize a ClinicalTrials.gov API v2 study into a public monitoring record.

overallStatus and studyType are stored separately, unmodified.
Expanded access is classified only from studyType == EXPANDED_ACCESS.
Contact names, emails, and phone numbers are dropped.
"""

from __future__ import annotations

import re
from typing import Any

from alsmon.util import as_date, dig, is_full_date, is_partial_date, nct_url, sha256_json

STRICT_ALS_PATTERNS = (
    re.compile(r"amyotrophic lateral sclerosis", re.IGNORECASE),
    re.compile(r"lou gehrig", re.IGNORECASE),
    re.compile(r"charcot disease", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z])ALS(?![A-Za-z])"),
)

# "Non-ALS" still contains the token ALS. Do not treat that as strict ALS
# unless another strict pattern also matches.
NON_ALS_PATTERN = re.compile(r"non[-\s]?als", re.IGNORECASE)
BROADER_MND_PATTERNS = (
    re.compile(r"motor neurone", re.IGNORECASE),
    re.compile(r"motor neuron", re.IGNORECASE),
    re.compile(r"kennedy", re.IGNORECASE),
    re.compile(r"spinal bulbar muscular", re.IGNORECASE),
    re.compile(r"spinal and bulbar", re.IGNORECASE),
    re.compile(r"primary lateral sclerosis", re.IGNORECASE),
    re.compile(r"progressive muscular atrophy", re.IGNORECASE),
    re.compile(r"progressive bulbar", re.IGNORECASE),
    re.compile(r"spinal muscular atrophy", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z])MND(?![A-Za-z])"),
    re.compile(r"(?<![A-Za-z])SBMA(?![A-Za-z])"),
)

DRUG_TYPES = {"DRUG", "BIOLOGICAL"}
EXPANDED_ACCESS = "EXPANDED_ACCESS"

PHASE_RANK = {
    "EARLY_PHASE1": 0,
    "PHASE1": 1,
    "PHASE2": 2,
    "PHASE3": 3,
    "PHASE4": 4,
    "NA": 5,
}


def condition_scope(conditions: list[str]) -> str:
    """Classify public condition strings.

    strict_als: a listed condition names ALS / Lou Gehrig / Charcot disease.
    broader_mnd: no strict ALS name, but a listed condition is another motor
    neuron disease (for example Kennedy's Disease).
    other: conditions are present and match neither group. query.cond=ALS can
    return those rows; they are not relabeled as motor neuron disease.
    unspecified: the API returned no condition strings.
    """
    cleaned = [c.strip() for c in conditions if isinstance(c, str) and c.strip()]
    if not cleaned:
        return "unspecified"
    text = " | ".join(cleaned)
    strict_hits = [pattern.search(text) for pattern in STRICT_ALS_PATTERNS]
    has_strict = any(strict_hits)
    if has_strict:
        only_als_token = (
            STRICT_ALS_PATTERNS[0].search(text) is None
            and STRICT_ALS_PATTERNS[1].search(text) is None
            and STRICT_ALS_PATTERNS[2].search(text) is None
            and NON_ALS_PATTERN.search(text) is not None
        )
        if only_als_token and any(pattern.search(text) for pattern in BROADER_MND_PATTERNS):
            return "broader_mnd"
        if only_als_token:
            return "other"
        return "strict_als"
    if any(pattern.search(text) for pattern in BROADER_MND_PATTERNS):
        return "broader_mnd"
    return "other"


def _sorted_phases(phases: list[str]) -> list[str]:
    unique = []
    seen = set()
    for phase in phases:
        if not isinstance(phase, str):
            continue
        token = phase.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return sorted(unique, key=lambda item: (PHASE_RANK.get(item, 99), item))


def _interventions(raw_items: Any) -> list[dict[str, str]]:
    if not isinstance(raw_items, list):
        return []
    collected = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        collected.append(
            {
                "type": str(item.get("type") or "").strip(),
                "name": str(item.get("name") or "").strip(),
            }
        )
    collected.sort(key=lambda item: (item["type"], item["name"]))
    return collected


def drug_biological_interventions(record: dict[str, Any]) -> list[dict[str, str]]:
    items = []
    for item in record.get("interventions") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").upper()
        if kind in DRUG_TYPES:
            items.append({"type": kind, "name": str(item.get("name") or "").strip()})
    items.sort(key=lambda item: (item["type"], item["name"]))
    return items


def _locations(raw_items: Any) -> list[dict[str, str]]:
    """Keep facility geography only. Drop contacts and other personal fields."""
    if not isinstance(raw_items, list):
        return []
    compact = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "facility": str(item.get("facility") or "").strip(),
                "city": str(item.get("city") or "").strip(),
                "country": str(item.get("country") or "").strip(),
                "status": str(item.get("status") or "").strip(),
            }
        )
    compact.sort(key=lambda loc: (loc["country"], loc["city"], loc["facility"], loc["status"]))
    return compact


def location_fingerprint(locations: list[dict[str, str]]) -> str:
    return sha256_json(locations)


def _outcome_measures(raw_items: Any) -> list[dict[str, str]]:
    if not isinstance(raw_items, list):
        return []
    measures = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        measures.append(
            {
                "type": str(item.get("type") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "timeFrame": str(item.get("timeFrame") or "").strip(),
                "paramType": str(item.get("paramType") or "").strip(),
                "unitOfMeasure": str(item.get("unitOfMeasure") or "").strip(),
            }
        )
    measures.sort(key=lambda item: (item["type"], item["title"], item["timeFrame"]))
    return measures


def results_fingerprint(payload: dict[str, Any]) -> str:
    return sha256_json(payload)


def normalize_study(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (record, errors). A record is None when it cannot be identified."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["study is not an object"]

    protocol = raw.get("protocolSection")
    if not isinstance(protocol, dict):
        protocol = {}

    nct_id = dig(protocol, "identificationModule", "nctId")
    if not isinstance(nct_id, str) or not nct_id.strip():
        return None, ["missing nctId"]
    nct_id = nct_id.strip()

    title = dig(protocol, "identificationModule", "briefTitle") or ""
    official = dig(protocol, "identificationModule", "officialTitle") or ""
    if not isinstance(title, str):
        title = ""
    if not isinstance(official, str):
        official = ""
    title = title.strip()
    official = official.strip()
    if not title:
        title = official
    if not title:
        errors.append(f"{nct_id}: missing title")

    overall_status = dig(protocol, "statusModule", "overallStatus")
    if not isinstance(overall_status, str) or not overall_status.strip():
        errors.append(f"{nct_id}: missing overallStatus")
        overall_status = ""
    else:
        overall_status = overall_status.strip()

    study_type = dig(protocol, "designModule", "studyType")
    if not isinstance(study_type, str) or not study_type.strip():
        errors.append(f"{nct_id}: missing studyType")
        study_type = ""
    else:
        study_type = study_type.strip()

    phases_raw = dig(protocol, "designModule", "phases") or []
    if phases_raw is None:
        phases_raw = []
    if not isinstance(phases_raw, list):
        errors.append(f"{nct_id}: phases is not a list")
        phases_raw = []

    conditions_raw = dig(protocol, "conditionsModule", "conditions") or []
    if not isinstance(conditions_raw, list):
        errors.append(f"{nct_id}: conditions is not a list")
        conditions_raw = []
    conditions = sorted({c.strip() for c in conditions_raw if isinstance(c, str) and c.strip()})

    interventions = _interventions(dig(protocol, "armsInterventionsModule", "interventions"))
    locations = _locations(dig(protocol, "contactsLocationsModule", "locations"))
    outcomes = _outcome_measures(dig(raw, "resultsSection", "outcomeMeasuresModule", "outcomeMeasures"))

    last_update_post = as_date(dig(protocol, "statusModule", "lastUpdatePostDateStruct"))
    study_first_post = as_date(dig(protocol, "statusModule", "studyFirstPostDateStruct"))
    last_update_submit = as_date(dig(protocol, "statusModule", "lastUpdateSubmitDate"))
    status_verified = as_date(dig(protocol, "statusModule", "statusVerifiedDate"))
    results_first_post = as_date(dig(protocol, "statusModule", "resultsFirstPostDateStruct"))
    results_first_submit = as_date(dig(protocol, "statusModule", "resultsFirstSubmitDate"))

    for label, value in (
        ("lastUpdatePostDate", last_update_post),
        ("studyFirstPostDate", study_first_post),
        ("lastUpdateSubmitDate", last_update_submit),
        ("resultsFirstPostDate", results_first_post),
        ("resultsFirstSubmitDate", results_first_submit),
    ):
        if not is_full_date(value):
            errors.append(f"{nct_id}: {label} is not YYYY-MM-DD ({value})")
    if not is_partial_date(status_verified):
        errors.append(f"{nct_id}: statusVerifiedDate is not a date ({status_verified})")

    has_results = bool(raw.get("hasResults"))
    results_payload = {
        "hasResults": has_results,
        "resultsFirstPostDate": results_first_post,
        "resultsFirstSubmitDate": results_first_submit,
        "outcomeMeasures": outcomes,
    }

    sponsor = dig(protocol, "sponsorCollaboratorsModule", "leadSponsor", "name") or ""
    if not isinstance(sponsor, str):
        sponsor = ""

    record = {
        "nctId": nct_id,
        "title": title,
        "officialTitle": official,
        "overallStatus": overall_status,
        "studyType": study_type,
        "isExpandedAccess": study_type == EXPANDED_ACCESS,
        "phases": _sorted_phases(phases_raw),
        "conditions": conditions,
        "conditionScope": condition_scope(conditions),
        "interventions": interventions,
        "sponsor": sponsor.strip(),
        "locations": locations,
        "locationFingerprint": location_fingerprint(locations),
        "hasResults": has_results,
        "resultsFirstPostDate": results_first_post,
        "resultsFirstSubmitDate": results_first_submit,
        "outcomeMeasures": outcomes,
        "resultsFingerprint": results_fingerprint(results_payload),
        "studyFirstPostDate": study_first_post,
        "lastUpdateSubmitDate": last_update_submit,
        "lastUpdatePostDate": last_update_post,
        "statusVerifiedDate": status_verified,
        "url": nct_url(nct_id),
        "firstSeenAt": None,
    }
    return record, errors
