"""The 2026-10-28 baseline stays frozen and matches the original export."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from support import BASELINE, BASELINE_META, ROOT

from alsmon.baseline import EXPECTED_BASELINE_SHA256, verify_baseline
from alsmon.constants import HISTORICAL_BROAD_COUNT, HISTORICAL_EMBEDDED_COUNT


class BaselineTests(unittest.TestCase):
    def test_frozen_file_matches_locked_history(self):
        meta = verify_baseline(BASELINE, BASELINE_META)
        records = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(len(records), HISTORICAL_EMBEDDED_COUNT)
        self.assertEqual(len({record["nct"] for record in records}), HISTORICAL_EMBEDDED_COUNT)
        self.assertEqual(meta["checksumSha256"], EXPECTED_BASELINE_SHA256)
        self.assertEqual(meta["scope"]["broadConditionSearchCount"], HISTORICAL_BROAD_COUNT)
        self.assertEqual(meta["scope"]["embeddedRecordCount"], 486)
        self.assertTrue(meta["frozen"])
        self.assertEqual(meta["snapshotTimestamp"], "2026-10-28T23:59:00-07:00")
        kennedy = next(record for record in records if record["nct"] == "NCT00004771")
        self.assertIn("Kennedy", kennedy["title"])
        self.assertEqual(
            meta["derivedFromRecords"]["legacyPageBuckets"]["mergedRecruitingLike"],
            81,
        )
        self.assertEqual(meta["derivedFromRecords"]["legacyPageBuckets"]["recruiting"], 44)
        self.assertEqual(meta["derivedFromRecords"]["codedPhaseAssignments"], 563)
        self.assertGreater(meta["derivedFromRecords"]["codedPhaseAssignments"], 486)

    def test_baseline_array_is_not_wrapped_or_rewritten_by_sync_layout(self):
        text = BASELINE.read_text(encoding="utf-8")
        self.assertTrue(text.lstrip().startswith("["))
        self.assertNotIn("scriptVersion", text)
        self.assertIn("https://clinicaltrials.gov/study/NCT00004771", text)
        self.assertTrue((ROOT / "data" / "baselines" / "2026-10-28.meta.json").exists())


if __name__ == "__main__":
    unittest.main()
