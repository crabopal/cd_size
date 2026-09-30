import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from cdsize.app import list_directory, open_window
from tests.sampledb import write_database

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def test_ui_calls_browse_with_explicit_flag(self):
        html = (ROOT / "cdsize" / "ui.html").read_text(encoding="utf-8")
        self.assertNotIn("cdn", html.lower())
        self.assertIn("browse(entry.path, false)", html)
        self.assertIn("browse(entry.path, true)", html)
        self.assertIn("browse(place.path, true)", html)
        self.assertIn("browse(path, false)", html)
        self.assertIn("{{VERSION}}", html)

    def test_hidden_files_and_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".secret").write_text("x", encoding="utf-8")
            (root / "mini.1CD").write_bytes(b"1")
            nested = root / "base"
            nested.mkdir()
            (nested / "1Cv8.1CD").write_bytes(b"1")
            (root / "notes.txt").write_text("x", encoding="utf-8")
            listed = list_directory(root)
        names = [item["name"] for item in listed["entries"]]
        self.assertNotIn(".secret", names)
        marked = {item["name"]: item for item in listed["entries"]}
        self.assertTrue(marked["mini.1CD"]["is_1cd"])
        self.assertTrue(marked["base"]["has_db"])
        self.assertFalse(marked["notes.txt"]["is_1cd"])

    def test_http_on_port_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            folder = Path(tmp) / "base"
            folder.mkdir()
            write_database(folder / "1Cv8.1CD", [{
                "name": "_Reference1",
                "fields": [("_A", "B", 0, 7)],
                "flags": [1, 0],
            }], page_size=4096)
            (Path(tmp) / ".hidden").write_text("no", encoding="utf-8")
            previous = os.environ.get("CDSIZE_HOME")
            os.environ["CDSIZE_HOME"] = str(home)
            server = None
            try:
                server, url = open_window(port=0, open_browser=False, initial_path=str(folder / "1Cv8.1CD"))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.assertTrue(url.startswith("http://127.0.0.1:"))
                address = (home / "адрес.txt").read_text(encoding="utf-8")
                self.assertIn("http://127.0.0.1:", address)
                base = url.split("?", 1)[0]
                page = _get(url)
                self.assertIn("0.2.1", page)
                self.assertIn("browse(entry.path, false)", page)
                places = json.loads(_get(base + "api/places"))
                self.assertTrue(any(item["path"] == "/" for item in places["places"]))
                listing = json.loads(_get(base + "api/list?path=" + _quote(tmp)))
                self.assertFalse(any(item["name"].startswith(".") for item in listing["entries"]))
                body = json.dumps({"path": str(folder)}).encode("utf-8")
                report = json.loads(_post(base + "api/inspect", body))
                self.assertEqual(report["tables"][0]["name"], "_Reference1")
                self.assertEqual(report["tables"][0]["purpose"], "справочник")
                exported = _get(base + "api/export?format=text&path=" + _quote(str(folder / "1Cv8.1CD")))
                self.assertIn("_Reference1", exported)
                empty = Path(tmp) / "empty"
                empty.mkdir()
                missing = json.loads(_post(base + "api/inspect", json.dumps({"path": str(empty)}).encode()))
                self.assertIn("нет файла 1Cv8.1CD", missing["error"])
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if previous is None:
                    os.environ.pop("CDSIZE_HOME", None)
                else:
                    os.environ["CDSIZE_HOME"] = previous


def _quote(path):
    from urllib.parse import quote
    return quote(path)


def _get(url):
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")


def _post(url, body):
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.read().decode("utf-8")
