"""Run every public builder mode through the same command-line interface."""
from itertools import combinations
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from fictional import save_archive, save_input
from preview_fictional import save_preview
from issued_fictional import save_issued


class BuilderCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="premonition-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = {"--input": save_input(self.root/"single"),
                        "--archive": save_archive(self.root/"archive"),
                        "--preview": save_preview(self.root/"preview")}
        issued, record, pin = save_issued(self.root/"issued")
        self.sources["--issued"] = issued
        self.record_flags = ["--record", str(record), "--record-sha256", pin]
        self.builder = Path(__file__).resolve().parents[1]/"build.py"

    def run_cli(self, *args):
        if "--issued" in args:
            args = (*args, *self.record_flags)
        return subprocess.run([sys.executable, "-B", str(self.builder), *map(str, args)],
                              capture_output=True, text=True)

    def test_each_mode_builds_its_own_pages_and_labels(self):
        for option, source in self.sources.items():
            with self.subTest(option=option):
                output = self.root/(option[2:]+"-output")
                result = self.run_cli(option, source, "--output", output)
                self.assertEqual(result.returncode, 0, result.stderr)
                pages = list(output.glob("*.html"))
                self.assertEqual(len(pages), 3 if option=="--archive" else 1)
                text = "".join(page.read_text(encoding="utf-8") for page in pages)
                label = "Issued forecasts" if option=="--issued" else "Fictional preview" if option=="--preview" else "Historical replay"
                self.assertIn(label, text)
                self.assertIn("data-fixture-id=", text)
                self.assertTrue((output/"styles.css").is_file())
                self.assertTrue((output/"favicon.svg").is_file())

    def test_modes_are_mutually_exclusive_before_writing(self):
        for first, second in combinations(self.sources, 2):
            with self.subTest(first=first, second=second):
                output = self.root/(first[2:]+second[2:])
                result = self.run_cli(first, self.sources[first], second, self.sources[second], "--output", output)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("not allowed with argument", result.stderr)
                self.assertFalse(output.exists())

    def test_genuine_input_requires_original_record_and_cannot_enter_other_modes(self):
        for i, option in enumerate(("--issued", "--preview", "--input", "--archive")):
            output = self.root/f"wrong-source-{i}"
            result = subprocess.run([sys.executable, "-B", str(self.builder), option, str(self.sources["--issued"]),
                                     "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
        result = self.run_cli("--preview", self.sources["--preview"], *self.record_flags, "--output", self.root/"wrong-record")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/"wrong-record").exists())

    def test_all_modes_preserve_existing_output(self):
        for option, source in self.sources.items():
            with self.subTest(option=option):
                output = self.root/(option[2:]+"-existing")
                output.mkdir()
                (output/"keep.txt").write_bytes(b"existing review")
                result = self.run_cli(option, source, "--output", output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("existing output is preserved", result.stderr)
                self.assertEqual({path.name:path.read_bytes() for path in output.iterdir()},
                                 {"keep.txt": b"existing review"})

    def test_all_modes_reject_output_in_git_worktrees(self):
        worktree = self.root/"worktree"
        worktree.mkdir()
        (worktree/".git").write_text("gitdir: external", encoding="utf-8")
        for option, source in self.sources.items():
            with self.subTest(option=option):
                output = worktree/option[2:]
                result = self.run_cli(option, source, "--output", output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("outside Git worktrees", result.stderr)
                self.assertFalse(output.exists())
