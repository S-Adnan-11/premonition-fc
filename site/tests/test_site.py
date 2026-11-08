"""Focused static-site checks using only fictional match inputs."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import BuildError, build, read_json, verified_input
from render import outcome_label
from fictional import sample, save_input


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="premonition-site-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_fictional_build_has_only_three_static_files(self):
        source = save_input(self.root/"input")
        result = build(source,self.root/"output")
        self.assertEqual(result["matches"],2)
        self.assertEqual({p.name for p in (self.root/"output").iterdir()},{"index.html","styles.css","favicon.svg"})

    def test_deterministic_output(self):
        source = save_input(self.root/"input")
        build(source,self.root/"first")
        build(source,self.root/"second")
        for path in (self.root/"first").iterdir():
            self.assertEqual(path.read_bytes(),(self.root/"second"/path.name).read_bytes())

    def test_zero_zero_and_independent_marks_are_rendered(self):
        source = save_input(self.root/"input")
        build(source,self.root/"output")
        page = (self.root/"output"/"index.html").read_text(encoding="utf-8")
        self.assertIn('data-actual-score>0 – 0</strong>',page)
        self.assertIn("Full-time draw",page)
        self.assertIn("Outcome: Incorrect",page)
        self.assertIn("Exact score: Correct",page)
        self.assertIn('data-summary="outcome">1<span>/2</span>',page)

    def test_native_disclosures_and_labels(self):
        source = save_input(self.root/"input")
        build(source,self.root/"output")
        page = (self.root/"output"/"index.html").read_text(encoding="utf-8")
        self.assertEqual(page.count('<details name="prediction">'),2)
        self.assertEqual(page.count('<summary>'),2)
        self.assertEqual(page.count('class="summary-action">View prediction '),2)
        self.assertIn('class="skip-link"',page)
        self.assertIn('lang="en"',page)
        self.assertNotIn("<script",page)

    def test_display_probabilities_use_original_ranking(self):
        data = sample()
        data["matches"][0]["forecast"]["probabilities"] = {"home_win":0.33331,"draw":0.33332,"away_win":0.33337}
        self.assertEqual(outcome_label(data["matches"][0]),"Vale City win")

    def test_text_is_escaped_in_text_and_attributes(self):
        data = sample()
        data["matches"][0]["home"]["name"] = '<b title="sample">Harbour & friends</b>'
        source = save_input(self.root/"input",data)
        build(source,self.root/"output")
        page = (self.root/"output"/"index.html").read_text(encoding="utf-8")
        self.assertIn('&lt;b title=&quot;sample&quot;&gt;Harbour &amp; friends&lt;/b&gt;',page)
        self.assertNotIn('<b title="sample">',page)

    def test_missing_input_or_adjoining_evidence_fails(self):
        with self.assertRaises(BuildError):
            build(self.root/"missing.json",self.root/"output")
        source = save_input(self.root/"input")
        source.with_name("proof_manifest.json").unlink()
        with self.assertRaises(BuildError):
            build(source,self.root/"output")
        self.assertFalse((self.root/"output").exists())

    def test_changed_input_or_schema_hash_fails(self):
        for filename in ("historical_display_input.json","display_input.schema.json"):
            folder = self.root/filename.replace(".","-")
            source = save_input(folder)
            target = source.with_name(filename)
            target.write_text(target.read_text(encoding="utf-8")+" ",encoding="utf-8")
            with self.subTest(file=filename),self.assertRaises(BuildError):
                build(source,self.root/(filename+"-out"))

    def test_malformed_json_duplicate_keys_and_nonfinite_numbers_fail(self):
        for i,text in enumerate(('{bad', '{"mode":"a","mode":"b"}', '{"p":NaN}')):
            path = self.root/f"bad-{i}.json"
            path.write_text(text,encoding="utf-8")
            with self.subTest(text=text),self.assertRaises(BuildError):
                read_json(path)

    def test_live_mode_is_rejected_even_with_updated_hash(self):
        data = sample()
        data["mode"] = "live"
        source = save_input(self.root/"input",data)
        with self.assertRaisesRegex(BuildError,"historical replay"):
            build(source,self.root/"output")

    def test_unexpected_real_issue_timestamp_is_rejected(self):
        data = sample()
        data["issued_at_utc"] = "2025-08-15T00:00:00Z"
        with self.assertRaises(BuildError):
            build(save_input(self.root/"input",data),self.root/"output")

    def test_wrong_model_or_provenance_is_rejected(self):
        for name,value in (("name","Forest"),("version","unknown")):
            data = sample()
            data["presentation_model"][name] = value
            with self.subTest(field=name),self.assertRaises(BuildError):
                build(save_input(self.root/name,data),self.root/(name+"-out"))

    def test_wrong_outcome_mass_or_score_order_is_rejected(self):
        for variant in ("mass","order"):
            data = sample()
            if variant=="mass":
                data["matches"][0]["forecast"]["probabilities"]["home_win"] = 0.99
            else:
                data["matches"][0]["forecast"]["scorelines"].reverse()
            with self.subTest(variant=variant),self.assertRaises(BuildError):
                build(save_input(self.root/variant,data),self.root/(variant+"-out"))

    def test_wrong_mark_identity_or_date_is_rejected(self):
        for variant in ("mark","identity","date"):
            data = sample()
            if variant=="mark":
                data["matches"][0]["marks"]["outcome"] = "correct"
            elif variant=="identity":
                data["matches"][0]["fixture_id"] = "wrong"
            else:
                data["matches"][0]["played_date_london"] = "2025-09-01"
            with self.subTest(variant=variant),self.assertRaises(BuildError):
                build(save_input(self.root/variant,data),self.root/(variant+"-out"))

    def test_pending_postponed_and_cancelled_cases_stay_out_of_site(self):
        for status in ("pending","postponed","cancelled"):
            data = sample()
            data["matches"][0]["status"] = status
            with self.subTest(status=status),self.assertRaises(BuildError):
                build(save_input(self.root/status,data),self.root/(status+"-out"))

    def test_private_paths_are_not_rendered(self):
        data = sample()
        data["matches"][0]["home"]["name"] = "Q:\\confidential\\input.json"
        with self.assertRaisesRegex(BuildError,"prohibited"):
            build(save_input(self.root/"input",data),self.root/"output")

    def test_existing_output_is_preserved(self):
        source = save_input(self.root/"input")
        output = self.root/"output"
        output.mkdir()
        (output/"original.txt").write_text("keep",encoding="utf-8")
        with self.assertRaises(BuildError):
            build(source,output)
        self.assertEqual((output/"original.txt").read_text(),"keep")

    def test_output_inside_worktree_is_rejected(self):
        source = save_input(self.root/"input")
        with self.assertRaisesRegex(BuildError,"outside Git"):
            build(source,Path(__file__).resolve().parents[1]/"test-output")


if __name__=="__main__":
    unittest.main()
