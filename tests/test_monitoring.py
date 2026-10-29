"""Offline tests for pagination, classification, diff, and failed syncs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, FixtureFetch, copy_baseline, load_json, sample_record

from alsmon.api import ApiError, PaginationError, fetch_all_pages, request_json
from alsmon.diff import diff_snapshots
from alsmon.metrics import compute_metrics
from alsmon.normalize import condition_scope, normalize_study
from alsmon.pipeline import run_sync
from alsmon.store import assert_not_baseline
from alsmon.validate import validate_records


def _pages():
    return {
        None: load_json(FIXTURES / "pagination" / "page1.json"),
        "PAGE2": load_json(FIXTURES / "pagination" / "page2.json"),
    }


class PaginationTests(unittest.TestCase):
    def test_pages_combine_to_total_count(self):
        fetched = fetch_all_pages(FixtureFetch(_pages()), sleeper=lambda _s: None, page_delay=0)
        self.assertEqual(fetched["totalCount"], 3)
        self.assertEqual(len(fetched["studies"]), 3)
        self.assertEqual(fetched["pagesFetched"], 2)
        ids = [study["protocolSection"]["identificationModule"]["nctId"] for study in fetched["studies"]]
        self.assertEqual(ids, ["NCT10000001", "NCT10000002", "NCT10000003"])

    def test_incomplete_page_is_an_error(self):
        pages = {None: load_json(FIXTURES / "incomplete_page.json")}
        with self.assertRaises(PaginationError):
            fetch_all_pages(FixtureFetch(pages), sleeper=lambda _s: None, page_delay=0)

    def test_schema_error_fixture_has_no_studies_list(self):
        payload = load_json(FIXTURES / "schema_error.json")
        with self.assertRaises(ApiError):
            fetch_all_pages(FixtureFetch({None: payload}), sleeper=lambda _s: None, page_delay=0)


class NormalizeAndMetricsTests(unittest.TestCase):
    def test_required_fields_time_fields_and_contact_stripping(self):
        raw = load_json(FIXTURES / "pagination" / "page1.json")["studies"][0]
        record, errors = normalize_study(raw)
        self.assertEqual(errors, [])
        self.assertIsNotNone(record)
        for field in (
            "nctId",
            "title",
            "overallStatus",
            "studyType",
            "lastUpdatePostDate",
            "studyFirstPostDate",
            "url",
        ):
            self.assertTrue(record[field], field)
        self.assertEqual(record["lastUpdatePostDate"], "2024-06-02")
        self.assertEqual(record["statusVerifiedDate"], "2024-06")
        self.assertEqual(record["phases"], ["PHASE1", "PHASE2"])
        blob = json.dumps(record)
        self.assertNotIn("secret@example.com", blob)
        self.assertNotIn("Pat Example", blob)
        self.assertNotIn("555-0100", blob)
        self.assertEqual(validate_records([record]), [])

    def test_invalid_date_fixture_fails_validation(self):
        raw = load_json(FIXTURES / "invalid_date.json")["studies"][0]
        _record, errors = normalize_study(raw)
        self.assertTrue(any("lastUpdatePostDate" in error for error in errors))

    def test_duplicate_nct_fixture_fails_uniqueness(self):
        studies = load_json(FIXTURES / "duplicate_nct.json")["studies"]
        records = []
        for raw in studies:
            record, errors = normalize_study(raw)
            self.assertEqual(errors, [])
            records.append(record)
        problems = validate_records(records)
        self.assertTrue(any("duplicate" in problem for problem in problems))

    def test_expanded_access_is_not_recruiting(self):
        studies = load_json(FIXTURES / "pagination" / "page1.json")["studies"]
        records = [normalize_study(raw)[0] for raw in studies]
        interventional = records[0]
        expanded = records[1]
        self.assertEqual(interventional["studyType"], "INTERVENTIONAL")
        self.assertFalse(interventional["isExpandedAccess"])
        self.assertEqual(interventional["overallStatus"], "RECRUITING")
        self.assertEqual(expanded["studyType"], "EXPANDED_ACCESS")
        self.assertTrue(expanded["isExpandedAccess"])
        self.assertEqual(expanded["overallStatus"], "AVAILABLE")
        metrics = compute_metrics(records)
        self.assertEqual(metrics["recordCount"], 2)
        self.assertEqual(metrics["statusCountSum"], 2)
        self.assertEqual(metrics["recruitingOnlyCount"], 1)
        self.assertEqual(metrics["expandedAccessCount"], 1)
        self.assertEqual(
            sum(1 for record in records if record["isExpandedAccess"] and record["overallStatus"] == "RECRUITING"),
            0,
        )

    def test_multi_phase_counts_overlap(self):
        record, errors = normalize_study(load_json(FIXTURES / "pagination" / "page1.json")["studies"][0])
        self.assertEqual(errors, [])
        metrics = compute_metrics([record])
        self.assertEqual(metrics["phaseCounts"]["PHASE1"], 1)
        self.assertEqual(metrics["phaseCounts"]["PHASE2"], 1)
        self.assertEqual(metrics["multiPhaseCount"], 1)
        self.assertGreater(metrics["phaseCountSum"], metrics["recordCount"])
        self.assertTrue(metrics["phaseCountsOverlap"])
        self.assertEqual(metrics["statusCountSum"], metrics["recordCount"])

    def test_condition_scope_distinguishes_strict_als_and_broader_mnd(self):
        self.assertEqual(condition_scope(["Amyotrophic Lateral Sclerosis"]), "strict_als")
        self.assertEqual(condition_scope(["ALS", "Kennedy's Disease"]), "strict_als")
        self.assertEqual(condition_scope(["Kennedy's Disease"]), "broader_mnd")
        self.assertEqual(condition_scope(["Non-ALS motor neuron disease"]), "broader_mnd")
        self.assertEqual(condition_scope(["Allergic Asthma"]), "other")
        self.assertEqual(condition_scope([]), "unspecified")
        broader, errors = normalize_study(load_json(FIXTURES / "pagination" / "page2.json")["studies"][0])
        self.assertEqual(errors, [])
        self.assertEqual(broader["conditionScope"], "broader_mnd")
        self.assertFalse(broader["isExpandedAccess"])


class DiffTests(unittest.TestCase):
    def test_tracked_changes_keep_old_and_new_values(self):
        original = sample_record()
        updated = sample_record(
            overallStatus="ACTIVE_NOT_RECRUITING",
            phases=["PHASE3"],
            interventions=[{"type": "DRUG", "name": "Other Drug"}],
            locations=[
                {
                    "facility": "Other Hospital",
                    "city": "Seattle",
                    "country": "United States",
                    "status": "RECRUITING",
                }
            ],
            hasResults=True,
            resultsFirstPostDate="2025-01-01",
            outcomeMeasures=[{"type": "PRIMARY", "title": "Strength", "timeFrame": "12 weeks", "paramType": "MEAN", "unitOfMeasure": "score"}],
        )
        added = sample_record(nctId="NCT10000099", title="Brand new ALS study", firstSeenAt="2026-10-29T12:00:00Z")
        detected = "2026-10-29T12:00:00Z"
        changes = diff_snapshots([original], [updated, added], detected_at=detected)
        by_type = {}
        for change in changes:
            by_type.setdefault(change["type"], []).append(change)

        self.assertIn("status_change", by_type)
        status = by_type["status_change"][0]
        self.assertEqual(status["old"], "RECRUITING")
        self.assertEqual(status["new"], "ACTIVE_NOT_RECRUITING")
        self.assertEqual(status["url"], "https://clinicaltrials.gov/study/NCT10000001")
        self.assertEqual(status["firstSeenAt"], original["firstSeenAt"])
        self.assertEqual(status["detectedAt"], detected)

        self.assertEqual(by_type["phase_change"][0]["old"], ["PHASE1", "PHASE2"])
        self.assertEqual(by_type["phase_change"][0]["new"], ["PHASE3"])
        self.assertEqual(by_type["intervention_change"][0]["new"], [{"type": "DRUG", "name": "Other Drug"}])
        self.assertEqual(by_type["location_update"][0]["new"]["locations"][0]["city"], "Seattle")
        self.assertEqual(by_type["results_published"][0]["new"]["hasResults"], True)
        self.assertNotIn("results_field_change", by_type)

        created = by_type["new_registration"][0]
        self.assertEqual(created["nctId"], "NCT10000099")
        self.assertIsNone(created["old"])
        self.assertEqual(created["url"], "https://clinicaltrials.gov/study/NCT10000099")
        self.assertEqual(created["firstSeenAt"], detected)
        self.assertEqual(created["detectedAt"], detected)

    def test_behavioral_only_edit_is_not_a_drug_change(self):
        original = sample_record()
        edited = sample_record(
            interventions=[
                {"type": "BEHAVIORAL", "name": "Different coaching"},
                {"type": "DRUG", "name": "Example Drug"},
            ]
        )
        changes = diff_snapshots([original], [edited], detected_at="2026-10-29T12:00:00Z")
        self.assertFalse(any(change["type"] == "intervention_change" for change in changes))

    def test_results_field_change_after_publication(self):
        original = sample_record(
            hasResults=True,
            resultsFirstPostDate="2024-01-01",
            outcomeMeasures=[{"type": "PRIMARY", "title": "Old", "timeFrame": "1 week", "paramType": "MEAN", "unitOfMeasure": "score"}],
        )
        edited = sample_record(
            hasResults=True,
            resultsFirstPostDate="2024-01-01",
            outcomeMeasures=[{"type": "PRIMARY", "title": "New", "timeFrame": "1 week", "paramType": "MEAN", "unitOfMeasure": "score"}],
        )
        changes = diff_snapshots([original], [edited], detected_at="2026-10-29T12:00:00Z")
        self.assertEqual([change["type"] for change in changes], ["results_field_change"])
        self.assertEqual(changes[0]["old"]["outcomeMeasures"][0]["title"], "Old")
        self.assertEqual(changes[0]["new"]["outcomeMeasures"][0]["title"], "New")

    def test_leaving_the_query_is_not_called_cancelled(self):
        original = sample_record()
        changes = diff_snapshots([original], [], detected_at="2026-10-29T12:00:00Z")
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertEqual(change["type"], "left_query_scope")
        self.assertNotEqual(change["type"], "cancelled")
        self.assertIn("cancelled", change["note"].lower())
        self.assertIn("Do not describe this as cancelled", change["note"])
        self.assertIn("不是", change["noteZh"])
        self.assertIn("取消", change["noteZh"])
        self.assertIsNone(change["new"])
        self.assertEqual(change["old"]["overallStatus"], "RECRUITING")
        self.assertTrue(change["url"].startswith("https://clinicaltrials.gov/study/"))


class SyncFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        copy_baseline(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_latest(self, records):
        latest = self.root / "data" / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        document = {"schemaVersion": 1, "scriptVersion": "1.1.0", "records": records}
        (latest / "studies.json").write_text(json.dumps(document), encoding="utf-8")
        (latest / "meta.json").write_text(
            json.dumps({"checksumSha256": "seed", "runStatus": "success", "broadConditionSearch": {"totalCount": 12}}),
            encoding="utf-8",
        )
        return latest / "studies.json"

    def test_pagination_fixture_writes_initial_snapshot_without_fake_new_trials(self):
        fetch = FixtureFetch(_pages(), broad_total=20)
        result = run_sync(self.root, page_fetch=fetch, now=__import__("datetime").datetime(2026, 10, 29, 12, 0, tzinfo=__import__("datetime").timezone.utc), write=True)
        self.assertEqual(result.status, "success", result.message)
        studies = json.loads((self.root / "data" / "latest" / "studies.json").read_text(encoding="utf-8"))
        self.assertEqual(len(studies["records"]), 3)
        blob = json.dumps(studies)
        self.assertNotIn("secret@example.com", blob)
        report = json.loads((self.root / "data" / "changes" / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["kind"], "initial_snapshot")
        self.assertEqual(report["changes"], [])
        self.assertNotIn("new_registration", report["summary"])
        scope = json.loads((self.root / "data" / "latest" / "scope_vs_baseline.json").read_text(encoding="utf-8"))
        self.assertTrue(scope["notNewTrials"])
        self.assertTrue(scope["notCancellations"])
        self.assertIn("NCT10000001", scope["onlyInCurrent"])
        self.assertEqual(scope["onlyInBaselineCount"], 486)
        self.assertIn("不是", scope["noteZh"])
        meta = json.loads((self.root / "data" / "latest" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["sourceUpdatedAt"], "2025-02-03")
        self.assertEqual(meta["syncedAt"], "2026-10-29T12:00:00Z")
        self.assertEqual(meta["broadConditionSearch"]["totalCount"], 20)
        self.assertEqual(meta["metrics"]["statusCountSum"], 3)
        self.assertTrue(meta["metrics"]["phaseCountsOverlap"])
        baseline_after = (self.root / "data" / "baselines" / "2026-10-28.json").read_bytes()
        from support import BASELINE
        self.assertEqual(baseline_after, BASELINE.read_bytes())

        second = run_sync(
            self.root,
            page_fetch=FixtureFetch(_pages(), broad_total=20),
            now=__import__("datetime").datetime(2026, 10, 30, 12, 0, tzinfo=__import__("datetime").timezone.utc),
            write=True,
        )
        self.assertEqual(second.status, "no_change", second.message)
        self.assertFalse(second.changed)

    def test_error_response_does_not_replace_latest(self):
        path = self._seed_latest([sample_record()])
        before = path.read_bytes()
        meta_before = (self.root / "data" / "latest" / "meta.json").read_bytes()
        fetch = FixtureFetch({None: load_json(FIXTURES / "schema_error.json")})
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.exit_code, 1, result.message)
        self.assertFalse(result.changed)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.root / "data" / "latest" / "meta.json").read_bytes(), meta_before)
        self.assertFalse((self.root / "data" / "changes" / "latest.json").exists())

    def test_empty_fixture_does_not_replace_latest(self):
        path = self._seed_latest([sample_record()])
        before = path.read_bytes()
        fetch = FixtureFetch({None: load_json(FIXTURES / "empty_dataset.json")})
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.status, "anomaly")
        self.assertIn("empty_dataset", result.anomalies)
        self.assertEqual(path.read_bytes(), before)

    def test_duplicate_fixture_does_not_replace_latest(self):
        path = self._seed_latest([sample_record()])
        before = path.read_bytes()
        fetch = FixtureFetch({None: load_json(FIXTURES / "duplicate_nct.json")})
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.status, "anomaly")
        self.assertIn("schema_invalid", result.anomalies)
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_date_does_not_replace_latest(self):
        path = self._seed_latest([sample_record()])
        before = path.read_bytes()
        fetch = FixtureFetch({None: load_json(FIXTURES / "invalid_date.json")})
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.status, "anomaly")
        self.assertEqual(path.read_bytes(), before)

    def test_sharp_drop_does_not_replace_latest(self):
        seeded = [sample_record(nctId=f"NCT3{index:07d}") for index in range(60)]
        path = self._seed_latest(seeded)
        before = path.read_bytes()
        template = load_json(FIXTURES / "invalid_date.json")["studies"][0]
        studies = []
        for index in range(10):
            raw = json.loads(json.dumps(template))
            raw["protocolSection"]["identificationModule"]["nctId"] = f"NCT4{index:07d}"
            raw["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2024-08-01"
            studies.append(raw)
        fetch = FixtureFetch({None: {"totalCount": 10, "studies": studies}})
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.status, "anomaly", result.message)
        self.assertIn("sharp_count_drop", result.anomalies)
        self.assertEqual(path.read_bytes(), before)

    def test_incomplete_pagination_does_not_replace_latest(self):
        path = self._seed_latest([sample_record()])
        before = path.read_bytes()
        fetch = FixtureFetch({None: load_json(FIXTURES / "incomplete_page.json")})
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_last_good_file_is_not_overwritten(self):
        path = self._seed_latest([sample_record()])
        path.write_text("{not-json", encoding="utf-8")
        before = path.read_bytes()
        fetch = FixtureFetch(_pages())
        result = run_sync(self.root, page_fetch=fetch, write=True)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("unreadable", result.message)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(fetch.calls, [])

    def test_sync_refuses_to_write_baseline_directory(self):
        with self.assertRaises(Exception):
            assert_not_baseline(self.root / "data" / "baselines" / "2026-10-28.json", self.root)

    def test_status_change_between_snapshots_is_reported(self):
        self._seed_latest([sample_record()])
        raw = json.loads(json.dumps(load_json(FIXTURES / "pagination" / "page1.json")["studies"][0]))
        raw["protocolSection"]["statusModule"]["overallStatus"] = "ACTIVE_NOT_RECRUITING"
        fetch = FixtureFetch({None: {"totalCount": 1, "studies": [raw]}}, broad_total=12)
        result = run_sync(
            self.root,
            page_fetch=fetch,
            now=__import__("datetime").datetime(2026, 10, 29, 15, 0, tzinfo=__import__("datetime").timezone.utc),
            write=True,
        )
        self.assertEqual(result.status, "success", result.message)
        report = json.loads((self.root / "data" / "changes" / "latest.json").read_text(encoding="utf-8"))
        kinds = [change["type"] for change in report["changes"]]
        self.assertIn("status_change", kinds)
        status = next(change for change in report["changes"] if change["type"] == "status_change")
        self.assertEqual(status["old"], "RECRUITING")
        self.assertEqual(status["new"], "ACTIVE_NOT_RECRUITING")
        self.assertIn("https://clinicaltrials.gov/study/NCT10000001", status["url"])


class RetryTests(unittest.TestCase):
    def test_retries_rate_limit_then_reads_json(self):
        import io
        import urllib.error

        calls = {"n": 0}
        waits = []

        def opener(request, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "rate limit",
                    {"Retry-After": "0"},
                    io.BytesIO(b"slow down"),
                )

            class Response:
                status = 200
                headers = {}

                def read(self):
                    return b'{"totalCount": 1, "studies": []}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return Response()

        payload = request_json("https://example.test/studies", sleeper=waits.append, retries=2, opener=opener)
        self.assertEqual(payload["totalCount"], 1)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(waits, [0.0])


if __name__ == "__main__":
    unittest.main()
