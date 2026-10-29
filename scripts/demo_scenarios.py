#!/usr/bin/env python3
"""Print three offline scenarios: new trial, status change, and a failed response.

Does not call ClinicalTrials.gov and does not modify the repository.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alsmon.api import ApiError  # noqa: E402
from alsmon.diff import diff_snapshots  # noqa: E402
from alsmon.pipeline import run_sync  # noqa: E402


def _record(**overrides):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from support import sample_record

    return sample_record(**overrides)


def main() -> int:
    detected = "2026-10-29T12:00:00Z"
    original = _record()
    added = _record(
        nctId="NCT10000099",
        title="Newly posted ALS drug study",
        firstSeenAt=detected,
    )
    print("SCENARIO 1 new_registration")
    created = diff_snapshots([original], [original, added], detected_at=detected)
    new_items = [change for change in created if change["type"] == "new_registration"]
    print(json.dumps(new_items, ensure_ascii=False, indent=2))

    print("SCENARIO 2 status_change")
    updated = _record(overallStatus="ACTIVE_NOT_RECRUITING")
    status_changes = [
        change
        for change in diff_snapshots([original], [updated], detected_at=detected)
        if change["type"] == "status_change"
    ]
    print(json.dumps(status_changes, ensure_ascii=False, indent=2))

    print("SCENARIO 3 error response; latest preserved")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = Path(__file__).resolve().parents[1] / "data" / "baselines"
        target = root / "data" / "baselines"
        target.mkdir(parents=True)
        (target / "2026-10-28.json").write_text((baseline / "2026-10-28.json").read_text(encoding="utf-8"), encoding="utf-8")
        (target / "2026-10-28.meta.json").write_text((baseline / "2026-10-28.meta.json").read_text(encoding="utf-8"), encoding="utf-8")
        latest = root / "data" / "latest"
        latest.mkdir()
        studies = {"schemaVersion": 1, "scriptVersion": "1.1.0", "records": [original]}
        path = latest / "studies.json"
        path.write_text(json.dumps(studies), encoding="utf-8")
        before = path.read_bytes()

        def fail(_params):
            raise ApiError("HTTP 500 from fixture")

        result = run_sync(
            root,
            page_fetch=fail,
            now=datetime(2026, 10, 29, 12, tzinfo=timezone.utc),
            write=True,
        )
        after = path.read_bytes()
        print(f"status={result.status} exit={result.exit_code}")
        print(result.message)
        print(f"latest preserved={before == after}")
        if before != after:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
