"""Archive checks with fictional slates and isolated proof bundles."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import BuildError, build, read_json, verified_archive
from render import slate_filename
from fictional import save_archive


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="premonition-archive-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = save_archive(self.root/"input")

    def edit_archive(self,change):
        data = read_json(self.source)
        change(data)
        write_json(self.source,data)

    def refresh_proof(self,entry):
        source = self.source.parent/entry["input"]
        proof = source.with_name("proof_manifest.json")
        manifest = read_json(proof)
        manifest["output_hashes"]["historical_display_input.json"] = hashlib.sha256(source.read_bytes()).hexdigest()
        write_json(proof,manifest)
        entry["proof_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()

    def test_archive_links_dates_and_match_disclosures(self):
        result = build(self.source,self.root/"output",archive=True)
        self.assertEqual((result["slates"],result["matches"]),(2,4))
        slates = verified_archive(self.source)
        page = (self.root/"output"/"index.html").read_text(encoding="utf-8")
        self.assertEqual(len(result["files"]),5)
        self.assertIn("The replay archive.",page)
        self.assertLess(page.index("22–23 August 2025"),page.index("15–16 August 2025"))
        for data in slates:
            filename = slate_filename(data)
            self.assertIn(f'href="{filename}"',page)
            self.assertIn(f'data-slate-id="{data["slate"]["id"]}"',page)
            replay = (self.root/"output"/filename).read_text(encoding="utf-8")
            self.assertIn('class="back-to-archive" href="index.html"',replay)
            self.assertIn("Historical replay",replay)
            self.assertIn(f'<time datetime="{data["slate"]["simulated_issue_date_london"]}">',replay)
            self.assertEqual(replay.count('<details name="prediction">'),2)
            for match in data["matches"]:
                self.assertIn(f'data-fixture-id="{match["fixture_id"]}"',replay)
            self.assertIn('data-actual-score>0 – 0</strong>',replay)
            self.assertIn("Outcome: Incorrect",replay)
            self.assertIn("Exact score: Correct",replay)
            self.assertIn("OpenFootball",replay)
            self.assertNotIn("<script",replay)
        self.assertEqual({p.name for p in (self.root/"output").iterdir()},set(result["files"]))

    def test_determinism_is_independent_of_archive_entry_order(self):
        build(self.source,self.root/"first",archive=True)
        self.edit_archive(lambda data:data["slates"].reverse())
        build(self.source,self.root/"second",archive=True)
        for path in (self.root/"first").iterdir():
            self.assertEqual(path.read_bytes(),(self.root/"second"/path.name).read_bytes())

    def test_cli_archive_and_single_slate_entry_points(self):
        entry = read_json(self.source)["slates"][0]
        for option,source in (("--archive",self.source),("--input",self.source.parent/entry["input"])):
            result = subprocess.run([sys.executable,"-B",str(Path(__file__).resolve().parents[1]/"build.py"),
                option,str(source),"--output",str(self.root/("cli-"+option[2:]))],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((self.root/("cli-"+option[2:])/"index.html").exists())

    def test_archive_mode_revision_allowlist_and_provenance_are_required(self):
        original = read_json(self.source)
        variants = [dict(original,mode="live"),dict(original,source_revision="unknown"),
            dict(original,schema_version="unknown"),dict(original,issued_at_utc="private"),
            dict(original,source_hashes={}),dict(original,source_hashes=[]),
            dict(original,source_hashes=dict(original["source_hashes"],extra="ab"*32)),
            dict(original,source_hashes=dict(original["source_hashes"],**{"frozen/models.joblib":"bad"})),
            dict(original,slates=[]),dict(original,slates=None)]
        for index,value in enumerate(variants):
            write_json(self.source,value)
            with self.subTest(index=index),self.assertRaises(BuildError):
                build(self.source,self.root/f"bad-{index}",archive=True)
            self.assertFalse((self.root/f"bad-{index}").exists())

    def test_duplicate_input_or_slate_is_rejected(self):
        self.edit_archive(lambda data:data["slates"].append(deepcopy(data["slates"][0])))
        with self.assertRaisesRegex(BuildError,"Duplicate"):
            build(self.source,self.root/"output",archive=True)
        self.assertFalse((self.root/"output").exists())

    def test_duplicate_slate_from_another_bundle_is_rejected(self):
        archive = read_json(self.source)
        first = self.source.parent/archive["slates"][0]["input"]
        second = self.source.parent/archive["slates"][1]["input"]
        for name in ("historical_display_input.json","display_input.schema.json","proof_manifest.json"):
            second.with_name(name).write_bytes(first.with_name(name).read_bytes())
        archive["slates"][1].update({key:archive["slates"][0][key] for key in ("proof_sha256","fixture_ids")})
        write_json(self.source,archive)
        with self.assertRaisesRegex(BuildError,"Duplicate archive slate or fixture"):
            build(self.source,self.root/"output",archive=True)

    def test_incomplete_or_wrong_fixture_membership_is_rejected(self):
        original = read_json(self.source)
        ids = original["slates"][1]["fixture_ids"]
        for index,values in enumerate((ids[:-1],ids+[ids[0]],ids+["unknown"],[],None,[True])):
            data = deepcopy(original)
            data["slates"][1]["fixture_ids"] = values
            write_json(self.source,data)
            with self.subTest(index=index),self.assertRaises(BuildError):
                build(self.source,self.root/f"bad-{index}",archive=True)
            self.assertFalse((self.root/f"bad-{index}").exists())

    def test_missing_match_fails_even_after_input_checksum_is_refreshed(self):
        archive = read_json(self.source)
        entry = archive["slates"][1]
        source = self.source.parent/entry["input"]
        data = read_json(source)
        data["matches"].pop()
        write_json(source,data)
        proof = source.with_name("proof_manifest.json")
        manifest = read_json(proof)
        manifest.update(fixture_count=1,outcome_correct=0,exact_score_correct=0,completed_zero_zero_fixtures=1)
        write_json(proof,manifest)
        self.refresh_proof(entry)
        write_json(self.source,archive)
        with self.assertRaisesRegex(BuildError,"slate membership"):
            build(self.source,self.root/"output",archive=True)
        self.assertFalse((self.root/"output").exists())

    def test_proof_pins_and_common_frozen_provenance_are_checked(self):
        archive = read_json(self.source)
        entry = archive["slates"][1]
        proof = (self.source.parent/entry["input"]).with_name("proof_manifest.json")
        manifest = read_json(proof)
        manifest["source_hashes"]["forecasts/predictions.json"] = "cd"*32
        write_json(proof,manifest)
        with self.assertRaisesRegex(BuildError,"proof checksum"):
            build(self.source,self.root/"changed-proof",archive=True)
        entry["proof_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
        write_json(self.source,archive)
        with self.assertRaisesRegex(BuildError,"source provenance"):
            build(self.source,self.root/"changed-source",archive=True)

    def test_nonhistorical_second_slate_fails_before_any_page_is_written(self):
        archive = read_json(self.source)
        entry = archive["slates"][1]
        source = self.source.parent/entry["input"]
        data = read_json(source)
        data["mode"] = "live"
        write_json(source,data)
        self.refresh_proof(entry)
        write_json(self.source,archive)
        with self.assertRaises(BuildError):
            build(self.source,self.root/"output",archive=True)
        self.assertFalse((self.root/"output").exists())

    def test_paths_cannot_leave_bundle_or_name_arbitrary_files(self):
        original = read_json(self.source)
        paths = ("../historical_display_input.json","/historical_display_input.json",
            "C:/historical_display_input.json","slates\\historical_display_input.json",
            "slates/./historical_display_input.json","slates//historical_display_input.json",
            "slates/data.json","https://example.com/historical_display_input.json",None)
        for index,path in enumerate(paths):
            data = deepcopy(original)
            data["slates"][0]["input"] = path
            write_json(self.source,data)
            with self.subTest(path=path),self.assertRaises(BuildError):
                build(self.source,self.root/f"bad-{index}",archive=True)

    def test_existing_preview_is_preserved_and_retry_uses_fresh_output(self):
        output = self.root/"output"
        build(self.source,output,archive=True)
        before = {path.name:path.read_bytes() for path in output.iterdir()}
        self.edit_archive(lambda data:data.update(mode="live"))
        with self.assertRaises(BuildError):
            build(self.source,output,archive=True)
        self.assertEqual(before,{path.name:path.read_bytes() for path in output.iterdir()})
        self.source = save_archive(self.root/"recovered-input")
        build(self.source,self.root/"recovered-output",archive=True)
        self.assertEqual(before,{path.name:path.read_bytes() for path in (self.root/"recovered-output").iterdir()})


if __name__=="__main__":
    unittest.main()
