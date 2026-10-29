"""The static page must keep loading external JSON and must not hardcode counts."""

from __future__ import annotations

import unittest
from pathlib import Path

from support import ROOT


class PageContractTests(unittest.TestCase):
    def test_page_loads_json_and_does_not_embed_the_baseline_array(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("const DATA", html)
        self.assertNotIn(">486<", html)
        self.assertNotIn(">1097<", html)
        self.assertNotIn(">81<", html)
        self.assertNotIn(">109<", html)
        self.assertIn("data/baselines/2026-10-28.json", html)
        self.assertIn("data/latest/studies.json", html)
        self.assertIn("data/changes/latest.json", html)
        self.assertIn("clinicaltrials.gov", html)
        for phrase in (
            "口径",
            "离开检索范围",
            "不是",
            "扩展使用",
            "分期",
            "最新变化",
            "ClinicalTrials.gov",
        ):
            self.assertIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
