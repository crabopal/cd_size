import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _zipcompat():
    spec = importlib.util.spec_from_file_location("zipcompat", ROOT / "packaging" / "zipcompat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ZipTests(unittest.TestCase):
    def test_directory_entries_and_attributes(self):
        pack = _zipcompat().pack_directory
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tree"
            (root / "examples").mkdir(parents=True)
            (root / "examples" / "mini.1CD").write_bytes(b"1CD")
            (root / "cdsize").write_bytes(b"#!/bin/sh\n")
            (root / "ПРОЧТИ.txt").write_text("привет", encoding="utf-8")
            linux = Path(tmp) / "linux.zip"
            windows = Path(tmp) / "windows.zip"
            pack(linux, root, create_system=3, executables={"cdsize"})
            pack(windows, root, create_system=0, executables={"cdsize"})
            self._check(linux, 3)
            self._check(windows, 0)

    def _check(self, path, system):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            self.assertIn("examples/", names)
            self.assertIn("examples/mini.1CD", names)
            self.assertIn("cdsize", names)
            self.assertFalse(any(name.startswith("cdsize-linux") or name.startswith("tree/") for name in names))
            for info in archive.infolist():
                self.assertEqual(info.create_system, system, info.filename)
                if info.filename.endswith("/"):
                    self.assertEqual(info.external_attr & 0xFF, 0x10, info.filename)
                    self.assertEqual(info.external_attr >> 16, 0o40755, info.filename)
                else:
                    self.assertEqual(info.external_attr & 0xFF, 0x20, info.filename)
                    self.assertNotEqual(info.external_attr, 0x81A40000, info.filename)
            cdsize = archive.getinfo("cdsize")
            self.assertEqual(cdsize.external_attr >> 16, 0o100755)
