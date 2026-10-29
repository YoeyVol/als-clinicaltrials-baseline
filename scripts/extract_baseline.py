#!/usr/bin/env python3
"""Copy the historical const DATA array out of index.html into data/baselines/.

Refuses to overwrite an existing frozen snapshot unless --force is passed.
The daily sync does not call this script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alsmon.baseline import BaselineError, write_baseline  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract the frozen 2026-10-28 baseline.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--html", default="index.html")
    parser.add_argument("--force", action="store_true", help="Overwrite the frozen file. Do not use in normal runs.")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    html_path = Path(args.html)
    if not html_path.is_absolute():
        html_path = root / html_path
    try:
        path = write_baseline(root, html_path.read_text(encoding="utf-8"), force=args.force)
    except BaselineError as exc:
        print(f"baseline extract failed: {exc}", file=sys.stderr)
        return 1
    print(f"Frozen baseline is at {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
