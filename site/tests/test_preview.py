"""Fictional lifecycle, immutable forecast, validation and entry-point checks."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import BuildError, build
from preview import marks_for, verified_preview
from fictional import save_input
from preview_fictional import later_preview, sample_preview, save_preview


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="premonition-preview-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def rejected(self, issued, preview):
        path = save_preview(self.root/"input", issued, preview)
        with self.assertRaises(BuildError):
            build(path, self.root/"output", preview=True)
        self.assertFalse((self.root/"output").exists())

    def test_same_saved_file_and_link_survive_kickoff_and_result_change(self):
        issued, before = sample_preview()
        first = save_preview(self.root/"input", issued, before, filename="before.json")
        frozen_bytes = first.with_name("issued_forecasts.json").read_bytes()
        after = save_preview(self.root/"input", issued, later_preview(before), filename="after.json")
        self.assertEqual(frozen_bytes, first.with_name("issued_forecasts.json").read_bytes())
        self.assertEqual(json.loads(first.read_text())["issued_sha256"], json.loads(after.read_text())["issued_sha256"])
        initial, final = verified_preview(first), verified_preview(after)
        by_id = {m["fixture_id"]: m for m in final["matches"]}
        for original in initial["matches"]:
            updated = by_id[original["fixture_id"]]
            for key in ("fixture_id", "forecast", "issued_at_utc", "home", "away", "original_kickoff_at_utc"):
                self.assertEqual(original[key], updated[key])
        build(first, self.root/"before", preview=True)
        build(after, self.root/"after", preview=True)
        class Links(HTMLParser):
            def __init__(self):
                super().__init__(); self.links = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "a" and attrs.get("class") == "fixture-link":
                    self.links.append(attrs["href"])
        links = []
        for folder in ("before", "after"):
            parser = Links(); parser.feed((self.root/folder/"index.html").read_text(encoding="utf-8"))
            links.append(set(parser.links))
        self.assertEqual(links[0], links[1])

    def test_upcoming_has_timestamps_disclosures_and_no_score_or_marks(self):
        source = save_preview(self.root/"input")
        build(source, self.root/"output", preview=True)
        page = (self.root/"output/index.html").read_text(encoding="utf-8")
        self.assertEqual(page.count('<details name="prediction">'), 6)
        self.assertIn("View prediction", page)
        self.assertIn("10 November 2026, 12:00:00 UTC", page)
        self.assertIn("Scheduled · Pending", page)
        self.assertIn("Team-strength Poisson", page)
        for excluded in ("data-actual-score", "data-mark=", "issued_sha256", "issued_forecasts.json", "<script", "form_poisson"):
            self.assertNotIn(excluded, page)

    def test_completed_zero_zero_and_each_pending_or_void_state(self):
        issued, before = sample_preview()
        source = save_preview(self.root/"input", issued, later_preview(before))
        rows = verified_preview(source)["matches"]
        self.assertEqual(rows[0]["marks"], {"outcome": "incorrect", "exact_score": "correct"})
        self.assertEqual(rows[1]["marks"], {"outcome": "correct", "exact_score": "incorrect"})
        self.assertEqual(rows[2]["actual_full_time"], {"home_goals": 0, "away_goals": 0})
        for row in rows[3:]:
            self.assertIsNone(row["actual_full_time"]); self.assertIsNone(row["marks"])
        build(source, self.root/"output", preview=True)
        page = (self.root/"output/index.html").read_text(encoding="utf-8")
        self.assertIn('data-actual-score>0 – 0</strong>', page)
        self.assertIn("Full-time draw", page)
        for label in ("Postponed · Pending", "Cancelled · Void", "Unresolved · Pending", "Originally scheduled"):
            self.assertIn(label, page)
        self.assertEqual(page.count('data-mark="outcome"'), 3)
        self.assertEqual(page.count('data-mark="exact_score"'), 3)

    def test_placeholder_scores_in_every_noncompleted_state_are_rejected(self):
        for status in ("scheduled", "postponed", "cancelled", "unresolved"):
            issued, preview = sample_preview()
            preview["updates"][0].update(status=status, actual_full_time={"home_goals": 0, "away_goals": 0})
            with self.subTest(status=status): self.rejected(issued, preview)

    def test_completed_requires_nonnegative_integer_score(self):
        for actual in (None, {}, {"home_goals": True, "away_goals": 0}, {"home_goals": -1, "away_goals": 0},
                       {"home_goals": 1.0, "away_goals": 0}):
            issued, preview = sample_preview()
            preview["updates"][0].update(status="completed", actual_full_time=actual)
            with self.subTest(actual=actual): self.rejected(issued, preview)

    def test_updated_identity_membership_and_status_must_reconcile(self):
        for variant in ("duplicate", "unknown", "missing", "state"):
            issued, preview = sample_preview()
            if variant == "duplicate": preview["updates"].append(deepcopy(preview["updates"][0]))
            if variant == "unknown": preview["updates"][0]["fixture_id"] = "unknown"
            if variant == "missing": preview["updates"].pop()
            if variant == "state": preview["updates"][0]["status"] = "finished"
            with self.subTest(variant=variant): self.rejected(issued, preview)

    def test_update_cannot_replace_forecast_or_issue_time_or_supply_marks(self):
        for key, value in (("forecast", {}), ("issued_at_utc", "2026-11-11T12:00:00Z"),
                           ("marks", {"outcome": "correct"}), ("raw_payload", {})):
            issued, preview = sample_preview(); preview["updates"][0][key] = value
            with self.subTest(key=key): self.rejected(issued, preview)

    def test_saved_forecast_checksum_change_is_rejected(self):
        source = save_preview(self.root/"input")
        target = source.with_name("issued_forecasts.json")
        target.write_bytes(target.read_bytes()+b" ")
        with self.assertRaisesRegex(BuildError, "checksum changed"):
            build(source, self.root/"output", preview=True)

    def test_saved_forecast_path_is_fixed_and_missing_file_fails(self):
        for value in ("../issued_forecasts.json", "other.json", "C:/input.json"):
            issued, preview = sample_preview(); preview["issued_file"] = value
            with self.subTest(value=value): self.rejected(issued, preview)
        source = save_preview(self.root/"input")
        source.with_name("issued_forecasts.json").unlink()
        with self.assertRaises(BuildError): verified_preview(source)

    def test_wrong_modes_labels_and_models_are_rejected(self):
        for location, key, value in (("preview", "mode", "real"), ("preview", "mode", "historical_replay"),
                ("preview", "label", "Upcoming"), ("preview", "schema_version", "v2"),
                ("issued", "mode", "real"), ("issued", "presentation_model", "form_poisson"),
                ("issued", "competition", "Premier League")):
            issued, preview = sample_preview(); (preview if location == "preview" else issued)[key] = value
            with self.subTest(key=key, value=value): self.rejected(issued, preview)

    def test_saved_identity_duplicates_names_and_extra_fields_fail(self):
        for variant in ("duplicate", "identity", "team", "name", "extra", "season"):
            issued, preview = sample_preview(); fixture = issued["fixtures"][0]
            if variant == "duplicate": issued["fixtures"].append(deepcopy(fixture))
            if variant == "identity": fixture["fixture_id"] = "changed"
            if variant == "team": fixture["home"]["id"] = "bad/id"
            if variant == "name": fixture["home"]["name"] = "Real Team"
            if variant == "extra": fixture["private_note"] = "excluded"
            if variant == "season": issued["season"] = "2026-28"
            with self.subTest(variant=variant): self.rejected(issued, preview)

    def test_times_must_be_explicit_utc_and_precede_kickoff(self):
        for location, key, value in (("fixture", "issued_at_utc", "2026-11-10T12:00:00"),
                ("fixture", "issued_at_utc", "2026-11-13T20:00:00Z"),
                ("fixture", "kickoff_at_utc", "2026-02-30T20:00:00Z"),
                ("update", "kickoff_at_utc", "2026-11-10T11:00:00Z"),
                ("update", "kickoff_at_utc", "2027-07-01T20:00:00Z")):
            issued, preview = sample_preview()
            (issued["fixtures"][0] if location == "fixture" else preview["updates"][0])[key] = value
            with self.subTest(value=value): self.rejected(issued, preview)

    def test_probability_ranking_and_marginal_contradictions_fail(self):
        for variant in ("sum", "boolean", "count", "order", "duplicate", "mass"):
            issued, preview = sample_preview(); forecast = issued["fixtures"][0]["forecast"]
            if variant == "sum": forecast["probabilities"]["draw"] = .9
            if variant == "boolean": forecast["probabilities"]["home_win"] = True
            if variant == "count": forecast["scorelines"].pop()
            if variant == "order": forecast["scorelines"].reverse()
            if variant == "duplicate": forecast["scorelines"][1] = deepcopy(forecast["scorelines"][0])
            if variant == "mass": forecast["scorelines"][0]["probability"] = .4
            with self.subTest(variant=variant): self.rejected(issued, preview)

    def test_original_values_and_documented_tie_order_choose_marks(self):
        issued, _ = sample_preview(); forecast = issued["fixtures"][0]["forecast"]
        actual = {"home_goals": 0, "away_goals": 1}
        forecast["probabilities"] = {"home_win": .33331, "draw": .33332, "away_win": .33337}
        self.assertEqual(marks_for(forecast, actual)["outcome"], "correct")
        forecast["probabilities"] = {"home_win": .4, "draw": .2, "away_win": .4}
        self.assertEqual(marks_for(forecast, actual)["outcome"], "incorrect")

    def test_text_escaping_and_private_output_scan(self):
        issued, preview = sample_preview()
        issued["fixtures"][0]["home"]["name"] = 'Fictional <b title="x">A & B</b>'
        source = save_preview(self.root/"input", issued, preview)
        build(source, self.root/"escaped", preview=True)
        self.assertIn('&lt;b title=&quot;x&quot;&gt;A &amp; B&lt;/b&gt;', (self.root/"escaped/index.html").read_text())
        issued["fixtures"][0]["home"]["name"] = "Fictional C:\\secret\\input.json"
        self.rejected(issued, preview)

    def test_deterministic_rebuild_and_fresh_output_recovery(self):
        source = save_preview(self.root/"input")
        for name in ("first", "second"): build(source, self.root/name, preview=True)
        for path in (self.root/"first").iterdir():
            self.assertEqual(path.read_bytes(), (self.root/"second"/path.name).read_bytes())
        original = (self.root/"first/index.html").read_bytes()
        with self.assertRaises(BuildError): build(source, self.root/"first", preview=True)
        self.assertEqual(original, (self.root/"first/index.html").read_bytes())

    def test_cli_preview_and_historical_modes_are_separate(self):
        preview = save_preview(self.root/"input")
        historical = save_input(self.root/"historical")
        script = Path(__file__).resolve().parents[1]/"build.py"
        cases = ((["--preview", str(preview)], True), (["--input", str(historical)], True),
                 (["--input", str(preview)], False), (["--preview", str(historical)], False),
                 (["--input", str(historical), "--preview", str(preview)], False))
        for i, (flags, success) in enumerate(cases):
            output = self.root/f"cli-{i}"
            result = subprocess.run([sys.executable, "-B", str(script), *flags, "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, success, result.stderr)
            self.assertEqual(output.exists(), success)


if __name__ == "__main__":
    unittest.main()
