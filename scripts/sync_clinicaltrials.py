#!/usr/bin/env python3
"""Sync the V1.1 ALS monitoring snapshot from ClinicalTrials.gov API v2.

Exits 0 when the last good snapshot is unchanged or a valid update was written.
Exits 1 on API, pagination, or storage errors.
Exits 2 when the new payload is anomalous (empty, schema break, sharp drop).
Error and anomaly exits do not modify data/latest.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alsmon.pipeline import check_repository, emit_github_output, run_sync  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync ALS ClinicalTrials.gov public registrations.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and diff, but do not write.")
    parser.add_argument("--check", action="store_true", help="Offline integrity check. No network.")
    parser.add_argument("--now", default=None, help="Override the detection timestamp (ISO-8601).")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    if args.check:
        result = check_repository(args.repo_root)
    else:
        result = run_sync(args.repo_root, now=now, write=not args.dry_run)
    print(result.message)
    emit_github_output(result)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
