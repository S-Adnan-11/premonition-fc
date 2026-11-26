"""Provenance, complete census, unchanged selected forecasts and failure recovery."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import BuildError, build
from display import digest
from issued import assemble_display, verified_issued
from issued_fictional import chain, sample_events, save_issued, write_json
from premonition_fc.storage import object_digest


class IssuedTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="premonition-issued-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path, self.record, self.pin = save_issued(self.root/"input")
        self.flags = {"issued": True, "record_path": self.record, "record_sha256": self.pin}

    def replace_display(self, change, repin=True):
        data = json.loads(self.path.read_text())
        change(data["display"])
        if repin:
            data["display_sha256"] = object_digest(data["display"])
        write_json(self.path, data)

    def rejected(self):
        with self.assertRaises(BuildError):
            build(self.path, self.root/"output", **self.flags)
        self.assertFalse((self.root/"output").exists())

    def test_all_ten_selected_forecasts_equal_saved_pairs_without_rounding(self):
        data = verified_issued(self.path, self.record, self.pin)
        source = sample_events()[1]["payload"]
        self.assertEqual(len(data["matches"]), 10)
        self.assertEqual(len({m["fixture_id"] for m in data["matches"]}), 10)
        for match in data["matches"]:
            row = next(r for r in source["forecasts"] if r["fixture_id"] == match["fixture_id"] and r["model"] == "team_strength_poisson")
            self.assertEqual(list(match["forecast"]["probabilities"].values()), row["probabilities"])
            self.assertEqual(match["forecast"]["scorelines"], row["scorelines"])
            self.assertEqual(match["issued_at_utc"], source["issued_at_utc"])
            self.assertIsNone(match["actual_full_time"])
            self.assertIsNone(match["marks"])

    def test_changed_forecast_with_recomputed_local_pin_is_rejected(self):
        def change(data):
            data["matches"][0]["forecast"]["probabilities"] = {"home_win": .49, "draw": .31, "away_win": .2}
        self.replace_display(change)
        with self.assertRaisesRegex(BuildError, "original issue record"):
            verified_issued(self.path, self.record, self.pin)
        self.rejected()

    def test_changed_ranked_scoreline_with_recomputed_pin_is_rejected(self):
        self.replace_display(lambda d: d["matches"][0]["forecast"]["scorelines"][0].update(probability=.121))
        self.rejected()

    def test_missing_duplicate_wrong_model_time_snapshot_and_extra_fields_rejected(self):
        original = self.path.read_bytes()
        changes = [lambda d: d["matches"].pop(), lambda d: d["matches"].append(deepcopy(d["matches"][0])),
                   lambda d: d["matches"].__setitem__(0, deepcopy(d["matches"][1])),
                   lambda d: d.update(presentation_model="form_poisson"),
                   lambda d: d.update(issued_at_utc="2026-11-15T09:30:48Z"),
                   lambda d: d.update(snapshot_as_of_utc="2026-11-26T00:00:00Z"),
                   lambda d: d.update(schedule_observed_at_utc="2026-11-26T00:00:00Z"),
                   lambda d: d["matches"][0].update(issued_at_utc="2026-11-15T09:30:48Z"),
                   lambda d: d["matches"][0].update(raw_payload={})]
        for change in changes:
            with self.subTest(change=change):
                self.path.write_bytes(original); self.replace_display(change); self.rejected()

    def test_placeholder_scores_and_completed_status_rejected(self):
        original = self.path.read_bytes()
        for status in ("scheduled", "postponed", "completed", "cancelled", "unresolved"):
            self.path.write_bytes(original)
            self.replace_display(lambda d: d["matches"][0].update(status=status, actual_full_time={"home_goals": 0, "away_goals": 0}))
            with self.subTest(status=status): self.rejected()

    def test_invalid_probability_and_score_shapes_rejected_even_with_pin(self):
        original = self.path.read_bytes()
        for value in (True, -1, 1.1, .99):
            self.path.write_bytes(original)
            self.replace_display(lambda d: d["matches"][0]["forecast"]["probabilities"].update(draw=value))
            with self.subTest(value=value): self.rejected()
        self.path.write_bytes(original)
        self.replace_display(lambda d: d["matches"][0]["forecast"]["scorelines"][0].update(home_goals=1.0))
        self.rejected()

    def test_wrong_mode_and_version_cannot_promote_preview(self):
        original = json.loads(self.path.read_text())
        for field, value in (("mode", "fictional_preview"), ("mode", "historical_replay"), ("schema_version", "v2")):
            data = deepcopy(original); data[field] = value; write_json(self.path, data)
            with self.subTest(field=field): self.rejected()

    def test_missing_record_bad_external_pin_and_replaced_record_rejected(self):
        for record, pin in ((None, self.pin), (self.record, None), (self.record, "f"*64)):
            with self.subTest(record=record, pin=pin), self.assertRaises(BuildError):
                verified_issued(self.path, record, pin)
        events = sample_events(); events[1]["payload"]["forecasts"][0]["probabilities"] = [.5, .25, .25]
        write_json(self.record, chain([e["payload"] for e in events]))
        self.rejected()

    def test_broken_chain_fit_pair_and_fixture_identity_rejected(self):
        for variant in ("chain", "fit", "freeze", "pair", "duplicate", "missing", "census", "mode", "time", "order"):
            events = sample_events(); issue = events[1]["payload"]
            if variant == "fit": issue["fit_sha256"] = "e"*64
            if variant == "freeze": issue["frozen_event_hash"] = "e"*64
            if variant == "pair": issue["forecasts"][0]["model"] = "unknown"
            if variant == "duplicate": issue["forecasts"].append(deepcopy(issue["forecasts"][0]))
            if variant == "missing": issue["forecasts"].pop()
            if variant == "census": issue["fixtures"][0] = deepcopy(issue["fixtures"][1])
            if variant == "mode": issue["mode"] = "synthetic"
            if variant == "time": issue["issued_at_utc"] = "2026-11-21T16:00:00Z"
            if variant == "order": issue["forecasts"][0]["probability_order"] = ["A", "D", "H"]
            if variant != "chain": events = chain([e["payload"] for e in events])
            else: events[1]["payload"]["issued_at_utc"] = "changed"
            write_json(self.record, events)
            with self.subTest(variant=variant), self.assertRaises(BuildError):
                assemble_display(self.record, digest(self.record))

    def test_rendered_snapshot_labels_precision_links_and_inventory(self):
        result = build(self.path, self.root/"output", **self.flags)
        self.assertEqual(result["matches"], 10)
        self.assertEqual(set(result["files"]), {"index.html", "styles.css", "favicon.svg"})
        page = (self.root/"output/index.html").read_text(encoding="utf-8")
        for text in ("Issued forecasts", "Schedule checked at issuance", "14 November 2026, 10:20:48.765432 UTC",
                     "14 November 2026, 10:20:05.123456 UTC", "not a live score feed", 'href="#matches">Back to slate'):
            self.assertIn(text, page)
        self.assertEqual(page.count('<details name="prediction">'), 10)
        self.assertEqual(page.count('class="fixture-link"'), 10)
        for text in ("Fictional preview", "Historical replay", "data-actual-score", "data-mark=", "form_poisson",
                     "paired-internals", "fit-parameters", "fit_sha256", "record_sha256", "source_ledger", str(self.root)):
            self.assertNotIn(text, page)

    def test_deterministic_rebuild_existing_output_and_failed_input_recovery(self):
        for name in ("first", "second"): build(self.path, self.root/name, **self.flags)
        files = {p.name: p.read_bytes() for p in (self.root/"first").iterdir()}
        self.assertEqual(files, {p.name: p.read_bytes() for p in (self.root/"second").iterdir()})
        self.replace_display(lambda d: d.update(label="Changed"), repin=False)
        with self.assertRaises(BuildError): build(self.path, self.root/"first", **self.flags)
        self.assertEqual(files, {p.name: p.read_bytes() for p in (self.root/"first").iterdir()})
        self.rejected()
        self.path, _, _ = save_issued(self.root/"input")
        build(self.path, self.root/"output", **self.flags)

    def test_assembly_cli_preserves_existing_files_and_rejects_worktrees(self):
        script = Path(__file__).resolve().parents[1]/"issued.py"
        output = self.root/"assembled.json"
        args = [sys.executable, "-B", str(script), "--record", str(self.record), "--record-sha256", self.pin, "--output"]
        first = subprocess.run([*args, str(output)], capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        original = output.read_bytes()
        self.assertNotEqual(subprocess.run([*args, str(output)], capture_output=True).returncode, 0)
        self.assertEqual(output.read_bytes(), original)
        worktree = self.root/"checkout"; worktree.mkdir(); (worktree/".git").write_text("gitdir: external")
        self.assertNotEqual(subprocess.run([*args, str(worktree/"display.json")], capture_output=True).returncode, 0)
        self.assertFalse((worktree/"display.json").exists())


if __name__ == "__main__":
    unittest.main()
