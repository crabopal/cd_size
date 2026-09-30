import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cdsize import __version__
from cdsize import cli
from tests.sampledb import write_database

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "examples" / "mini.1CD"


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "cdsize", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class CliTests(unittest.TestCase):
    def test_version(self):
        result = _run(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn(__version__, result.stdout)
        self.assertIn("0.2.1", result.stdout)

    def test_report_without_path(self):
        for args in (["--json"], ["--html"], ["--match", "A"], ["--limit", "1"], ["--no-records"]):
            result = _run(args)
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("путь", result.stderr)

    def test_sort_alone_opens_window(self):
        calls = []

        def fake_serve(**kwargs):
            calls.append(kwargs)
            return 0

        original = cli.serve
        cli.serve = fake_serve
        try:
            self.assertEqual(cli.main([]), 0)
            self.assertEqual(cli.main(["--sort", "name"]), 0)
            self.assertEqual(cli.main(["--app", "--no-browser", "--port", "9", str(MINI)]), 0)
        finally:
            cli.serve = original
        self.assertEqual(len(calls), 3)
        self.assertFalse(calls[2]["open_browser"])
        self.assertEqual(calls[2]["port"], 9)
        self.assertEqual(calls[2]["initial_path"], str(MINI))

    def test_mini_limit_and_json(self):
        limited = _run([str(MINI), "--limit", "1"])
        self.assertEqual(limited.returncode, 0)
        self.assertIn("_AccumRg3", limited.stdout)
        payload = json.loads(_run([str(MINI), "--json", "--match", "ibversion"]).stdout)
        self.assertEqual([row["name"] for row in payload["tables"]], ["IBVERSION"])
        self.assertEqual(payload["version"], "0.2.1")
        html = _run([str(MINI), "--html", "--sort", "name"]).stdout
        self.assertIn("<table", html)
        self.assertIn("_AccumRg3", html)
        quiet = json.loads(_run([str(MINI), "--json", "--no-records"]).stdout)
        self.assertIsNone(quiet["tables"][0]["occupied"])

    def test_directory_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            base.mkdir()
            write_database(base / "1Cv8.1CD", [{
                "name": "T",
                "fields": [("_A", "B", 0, 7)],
                "flags": [1, 0],
            }], page_size=4096)
            ok = _run([str(base)])
            self.assertEqual(ok.returncode, 0)
            self.assertIn("T", ok.stdout)
            empty = Path(tmp) / "empty"
            empty.mkdir()
            missing_db = _run([str(empty)])
            self.assertEqual(missing_db.returncode, 2)
            self.assertIn("нет файла 1Cv8.1CD", missing_db.stderr)
            bad = Path(tmp) / "bad.1CD"
            bad.write_bytes(b"XXXXXXXX" + b"\x00" * 32)
            broken = _run([str(bad)])
            self.assertEqual(broken.returncode, 2)
            absent = _run([str(Path(tmp) / "nope.1CD")])
            self.assertEqual(absent.returncode, 2)
