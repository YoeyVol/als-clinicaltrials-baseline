#!/usr/bin/env python3
"""Print a pull-request body for a monitoring snapshot. Does not merge anything."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alsmon.store import RepoPaths  # noqa: E402


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    paths = RepoPaths.from_root(root)
    if not paths.changes_latest.exists():
        print("No change report was written.")
        return 0
    report = json.loads(paths.changes_latest.read_text(encoding="utf-8"))
    scope = report.get("scopeReview") or {}
    summary = report.get("summary") or {}
    lines = [
        "## ClinicalTrials.gov ALS sync",
        "",
        "Automated monitoring pull request. **Do not auto-merge.** Review the change record, then merge by hand if the diff is expected.",
        "",
        f"- Kind: `{report.get('kind')}`",
        f"- Detected at: `{report.get('detectedAt')}`",
        f"- Script: `{report.get('scriptVersion')}`",
        f"- Records: `{report.get('previousRecordCount')}` → `{report.get('currentRecordCount')}`",
        f"- Snapshot: `{report.get('currentSnapshotId')}`",
        "",
        "### Tracked changes",
        "",
    ]
    if summary:
        for name, count in summary.items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- No tracked field changes.")
    lines.extend(
        [
            "",
            "### Scope versus the frozen 2026-10-28 baseline",
            "",
            scope.get("note") or "",
            "",
            f"- Intersection: {scope.get('intersectionCount')}",
            f"- Only in the frozen baseline: {scope.get('onlyInBaselineCount')}",
            f"- Only in the current query: {scope.get('onlyInCurrentCount')}",
            "",
            "Those NCT set differences are a scope review. They are not new trials and not cancellations.",
            "",
            "Full report: `data/changes/latest.json`.",
            "",
        ]
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
