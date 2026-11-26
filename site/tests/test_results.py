"""Complete factual census, immutable forecasts, correction attribution and display marks."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from build import BuildError, build
from display import digest, read_json
from issued import verified_issued
from issued_fictional import write_json
from premonition_fc.storage import object_digest
from results_fictional import append_correction, change_review, save_results


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="premonition-results-test-"); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.record, self.pin, self.results = save_results(self.root/"input")
        self.flags = dict(issued=True, record_path=self.record, record_sha256=self.pin, results_path=self.results)

    def data(self):
        return verified_issued(self.source, self.record, self.pin, results_path=self.results)

    def rejected(self):
        with self.assertRaises(BuildError): build(self.source, self.root/"output", **self.flags)
        self.assertFalse((self.root/"output").exists())

    def test_factual_marks_zero_zero_and_unchanged_original_predictions(self):
        original = verified_issued(self.source, self.record, self.pin)
        updated = self.data()
        self.assertEqual(updated["snapshot_as_of_utc"], "2026-11-24T10:03:00Z")
        for old, new in zip(original["matches"], updated["matches"]):
            for field in ("forecast", "fixture_id", "issued_at_utc", "schedule_checked_at_utc", "kickoff_at_utc"):
                self.assertEqual(old[field], new[field])
        rows = updated["matches"]
        self.assertEqual(rows[0]["actual_full_time"], {"home_goals": 0, "away_goals": 0})
        self.assertEqual(rows[1]["marks"], {"outcome": "incorrect", "exact_score": "correct"})
        self.assertEqual(rows[2]["marks"], {"outcome": "correct", "exact_score": "incorrect"})
        for row in rows[3:]: self.assertIsNone(row["actual_full_time"]); self.assertIsNone(row["marks"])
        self.assertEqual(rows[3]["reviewed_kickoff_at_utc"], "2026-11-30T15:00:00Z")

    def test_complete_census_identity_and_issue_binding(self):
        old = read_json(self.results.parent/"reviewed_facts.json")
        variants = (lambda d:d["results"].pop(), lambda d:d["results"].append(deepcopy(d["results"][0])),
                    lambda d:d["results"][0].update(fixture_id="2026-27:unknown:unknown"),
                    lambda d:d.update(expected_fixture_ids=d["expected_fixture_ids"][:-1]),
                    lambda d:d.update(original_issue_event_hash="f"*64))
        for change in variants:
            write_json(self.results.parent/"reviewed_facts.json", old)
            change_review(self.results, change)
            with self.subTest(change=change): self.rejected()

    def test_altered_forecast_with_recomputed_pin_still_fails(self):
        data = read_json(self.source)
        data["display"]["matches"][0]["forecast"]["probabilities"] = {"home_win": .49, "draw": .31, "away_win": .2}
        data["display_sha256"] = object_digest(data["display"]); write_json(self.source, data)
        self.rejected()

    def test_unverified_contradictory_placeholder_and_unknown_finals_fail(self):
        old = read_json(self.results.parent/"reviewed_facts.json")
        changes = (lambda d:d["results"][0].update(actual_full_time=None),
                   lambda d:d["results"][0].update(actual_full_time={"home_goals": True, "away_goals": 0}),
                   lambda d:d["results"][0].update(played_date_london=None),
                   lambda d:d["results"][0].update(gaps=["Conflicting final scores."]),
                   lambda d:d["results"][0].update(status="awarded"),
                   lambda d:d["results"][0].update(status="unresolved"),
                   lambda d:d["results"][4].update(actual_full_time={"home_goals": 0, "away_goals": 0}),
                   lambda d:d["results"][0].update(evidence_document_ids=[]))
        for change in changes:
            write_json(self.results.parent/"reviewed_facts.json", old); change_review(self.results, change)
            with self.subTest(change=change): self.rejected()

    def test_source_hash_authority_observation_and_precision_checks(self):
        old = read_json(self.results.parent/"reviewed_facts.json")
        changes = (lambda d:d["documents"][0].update(sha256="f"*64),
                   lambda d:d["documents"][0].update(source_url="https://example.com/result"),
                   lambda d:d["documents"][0].update(source_url="https://www.premierleague.com.attacker.test/result"),
                   lambda d:d["documents"][0].update(relative_path="../escaped.txt"),
                   lambda d:d["documents"][0].update(observed_at_utc="2026-11-25T12:00:00Z"),
                   lambda d:d["results"][0].update(precision="scheduled_date"),
                   lambda d:d["results"][0].update(played_date_london="2026-11-30"),
                   lambda d:d["results"][0].update(verified_at_utc="2026-11-24T09:00:00Z"))
        for change in changes:
            write_json(self.results.parent/"reviewed_facts.json", old); change_review(self.results, change)
            with self.subTest(change=change): self.rejected()

    def test_access_failures_only_support_unresolved_rows(self):
        def blocked(d):
            d["documents"][0].update(http_status=403, relative_path=None, sha256=None, precision="unavailable")
            for row in d["results"]:
                row.update(status="unresolved", actual_full_time=None, played_date_london=None, kickoff_at_utc=None,
                           precision="unavailable", gaps=["Official page access failed."])
        change_review(self.results, blocked)
        self.assertTrue(all(row["status"] == "unresolved" for row in self.data()["matches"]))
        change_review(self.results, lambda d:d["results"][0].update(status="completed", actual_full_time={"home_goals": 0, "away_goals": 0}, played_date_london="2026-11-21", precision="date", gaps=[]))
        self.rejected()

    def test_indexed_evidence_has_explicit_transport_and_no_origin_status_claim(self):
        change_review(self.results, lambda d:d["documents"][0].update(transport="indexed_official_text", http_status=None, semantics="Fictional saved official indexed text; cache freshness unknown."))
        self.assertEqual(self.data()["matches"][0]["status"], "completed")
        change_review(self.results, lambda d:d["documents"][0].update(http_status=200))
        self.rejected()

    def test_corrections_keep_prior_review_and_require_attribution(self):
        original = (self.results.parent/"reviewed_facts.json").read_bytes()
        append_correction(self.results)
        self.assertEqual(original, (self.results.parent/"reviewed_facts.json").read_bytes())
        self.assertEqual(self.data()["matches"][0]["actual_full_time"], {"home_goals": 1, "away_goals": 0})
        change_review(self.results, lambda d:d["results"][0]["correction"].update(previous_result_sha256="f"*64))
        self.rejected()

    def test_unattributed_terminal_change_or_missing_correction_history_fails(self):
        append_correction(self.results, attribute=False); self.rejected()
        change_review(self.results, lambda d:d.update(previous_review_sha256=None)); self.rejected()

    def test_display_rendering_determinism_and_output_preservation(self):
        before = digest(self.record), self.source.read_bytes()
        for name in ("first", "second"):build(self.source, self.root/name, **self.flags)
        files = {p.name:p.read_bytes() for p in (self.root/"first").iterdir()}
        self.assertEqual(files, {p.name:p.read_bytes() for p in (self.root/"second").iterdir()})
        page = files["index.html"].decode()
        for expected in ("24 November 2026, 10:03:00 UTC", "Full-time draw", "Played", "London date", "Reviewed scheduled kickoff", "Unresolved", "Cancelled", 'data-actual-score>0 – 0'):
            self.assertIn(expected, page)
        self.assertEqual(page.count('data-mark="outcome"'), 3)
        self.assertEqual(page.count('data-mark="exact_score"'), 3)
        for forbidden in ("source_url", "sha256", "reviewed_facts.json", "fictional-official.txt", str(self.root), "form_poisson"):
            self.assertNotIn(forbidden, page)
        with self.assertRaises(BuildError):build(self.source, self.root/"first", **self.flags)
        self.assertEqual(files, {p.name:p.read_bytes() for p in (self.root/"first").iterdir()})
        self.assertEqual(before, (digest(self.record), self.source.read_bytes()))

    def test_explicit_cli_and_no_update_entrypoint_remains_compatible(self):
        script = Path(__file__).resolve().parents[1]/"build.py"
        common = [sys.executable, "-B", str(script), "--issued", str(self.source), "--record", str(self.record), "--record-sha256", self.pin]
        for name, extra in (("original", []), ("updated", ["--results", str(self.results)])):
            result = subprocess.run([*common, *extra, "--output", str(self.root/name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        page = (self.root/"original/index.html").read_text(encoding="utf-8")
        self.assertIn("All ten results remain pending", page)
        self.assertNotIn("data-mark=", page)
        result = subprocess.run([sys.executable, "-B", str(script), "--preview", str(self.source), "--results", str(self.results), "--output", str(self.root/"wrong-mode")], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0); self.assertFalse((self.root/"wrong-mode").exists())


if __name__ == "__main__":unittest.main()
