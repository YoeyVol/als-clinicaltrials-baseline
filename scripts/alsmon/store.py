"""Read and write monitoring files. Baseline snapshots are not writable here."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alsmon.constants import BASELINE_FILENAME, BASELINE_ID


class StoreError(Exception):
    pass


@dataclass(frozen=True)
class RepoPaths:
    root: Path
    baseline: Path
    baseline_meta: Path
    studies: Path
    meta: Path
    scope: Path
    changes_dir: Path
    changes_latest: Path
    changes_index: Path
    registry: Path

    @classmethod
    def from_root(cls, root: Path) -> RepoPaths:
        root = Path(root)
        baseline_dir = root / "data" / "baselines"
        latest = root / "data" / "latest"
        changes = root / "data" / "changes"
        return cls(
            root=root,
            baseline=baseline_dir / BASELINE_FILENAME,
            baseline_meta=baseline_dir / f"{BASELINE_ID}.meta.json",
            studies=latest / "studies.json",
            meta=latest / "meta.json",
            scope=latest / "scope_vs_baseline.json",
            changes_dir=changes,
            changes_latest=changes / "latest.json",
            changes_index=changes / "index.json",
            registry=root / "data" / "registry" / "first_seen.json",
        )


def assert_not_baseline(path: Path, root: Path) -> None:
    resolved = path.resolve()
    baseline_dir = (root / "data" / "baselines").resolve()
    if resolved == baseline_dir or baseline_dir in resolved.parents:
        raise StoreError(f"refusing to write frozen baseline path: {path}")


def atomic_write_many(root: Path, files: dict[Path, str]) -> None:
    """Write every file to a temp sibling, then replace. Baselines are rejected."""
    temps: list[tuple[Path, Path]] = []
    try:
        for path, text in files.items():
            assert_not_baseline(path, root)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            temps.append((temporary, path))
        for temporary, path in temps:
            os.replace(temporary, path)
    finally:
        for temporary, _path in temps:
            if temporary.exists():
                temporary.unlink()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_studies_document(path: Path) -> dict[str, Any] | None:
    """Load the last good snapshot. Missing file means there is no snapshot yet.

    A present but unreadable file is an error: the sync must not overwrite it.
    """
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"last good snapshot is unreadable; refusing to overwrite ({exc})") from exc
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise StoreError("last good snapshot schema is broken; refusing to overwrite")
    return document


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"unable to read {path} ({exc})") from exc
    if not isinstance(document, dict):
        raise StoreError(f"{path} is not a JSON object")
    return document


def load_baseline_ids(path: Path) -> list[str]:
    if not path.exists():
        raise StoreError(f"frozen baseline is missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise StoreError("frozen baseline must be a JSON array")
    ids = []
    for record in document:
        if isinstance(record, dict) and isinstance(record.get("nct"), str):
            ids.append(record["nct"])
    return ids
