"""Shared helpers for offline monitoring tests."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from alsmon.api import is_broad_count_request  # noqa: E402
from alsmon.normalize import location_fingerprint, results_fingerprint  # noqa: E402
from alsmon.util import nct_url  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASELINE = ROOT / "data" / "baselines" / "2026-10-28.json"
BASELINE_META = ROOT / "data" / "baselines" / "2026-10-28.meta.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def copy_baseline(repo: Path) -> None:
    target = repo / "data" / "baselines"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(BASELINE, target / "2026-10-28.json")
    shutil.copy(BASELINE_META, target / "2026-10-28.meta.json")


def sample_record(**overrides) -> dict:
    record = {
        "nctId": "NCT10000001",
        "title": "Phase 1/2 study of Example Drug in ALS",
        "officialTitle": "Official",
        "overallStatus": "RECRUITING",
        "studyType": "INTERVENTIONAL",
        "isExpandedAccess": False,
        "phases": ["PHASE1", "PHASE2"],
        "conditions": ["Amyotrophic Lateral Sclerosis"],
        "conditionScope": "strict_als",
        "interventions": [
            {"type": "BEHAVIORAL", "name": "Coaching"},
            {"type": "DRUG", "name": "Example Drug"},
        ],
        "sponsor": "Example Sponsor",
        "locations": [
            {
                "facility": "General Hospital",
                "city": "Boston",
                "country": "United States",
                "status": "RECRUITING",
            }
        ],
        "hasResults": False,
        "resultsFirstPostDate": None,
        "resultsFirstSubmitDate": None,
        "outcomeMeasures": [],
        "studyFirstPostDate": "2024-01-15",
        "lastUpdateSubmitDate": "2024-06-01",
        "lastUpdatePostDate": "2024-06-02",
        "statusVerifiedDate": "2024-06",
        "firstSeenAt": "2026-10-28T23:59:00-07:00",
    }
    record.update(overrides)
    record["isExpandedAccess"] = record["studyType"] == "EXPANDED_ACCESS"
    record["url"] = nct_url(record["nctId"])
    record["locationFingerprint"] = location_fingerprint(record["locations"])
    record["resultsFingerprint"] = results_fingerprint(
        {
            "hasResults": record["hasResults"],
            "resultsFirstPostDate": record["resultsFirstPostDate"],
            "resultsFirstSubmitDate": record["resultsFirstSubmitDate"],
            "outcomeMeasures": record["outcomeMeasures"],
        }
    )
    return record


class FixtureFetch:
    """Offline page fetch. Broad-count calls are separate from study pages."""

    def __init__(self, pages: dict, broad_total=12, error=None):
        self.pages = pages
        self.broad_total = broad_total
        self.error = error
        self.calls = []

    def __call__(self, params: dict):
        self.calls.append(dict(params))
        if self.error is not None and not is_broad_count_request(params):
            raise self.error
        if is_broad_count_request(params):
            if self.broad_total is None:
                raise self.error or RuntimeError("broad count unavailable")
            return {"totalCount": self.broad_total, "studies": []}
        token = params.get("pageToken")
        if token not in self.pages:
            raise AssertionError(f"unexpected page token {token!r}")
        return self.pages[token]
