import struct
import tempfile
import unittest
from pathlib import Path

from cdsize.reader import FormatError, old_alloc_page_count, open_database
from cdsize.report import format_size, render_text
from tests.sampledb import build_mini, write_database

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "examples" / "mini.1CD"


def _simple(name="T", flags=None, **kwargs):
    flags = [1, 0] if flags is None else flags
    table = {"name": name, "fields": [("_A", "B", 0, 7)], "flags": flags}
    table.update(kwargs)
    return table


class ReaderTests(unittest.TestCase):
    def test_version_comparison_note(self):
        self.assertTrue((8, 3, 8, 0) >= (8, 3, 8))
        self.assertFalse((8, 2, 14, 0) >= (8, 3, 8))

    def test_old_alloc_pages(self):
        self.assertEqual(old_alloc_page_count(0, 4096), 0)
        self.assertEqual(old_alloc_page_count(1, 4096), 1)
        self.assertEqual(old_alloc_page_count(1023 * 4096, 4096), 1)
        self.assertEqual(old_alloc_page_count(1023 * 4096 + 1, 4096), 2)

    def test_format_838(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(path, [_simple()], version=(8, 3, 8, 0), page_size=8192, locale="ru_RU")
            db = open_database(path)
        self.assertEqual(db.version, (8, 3, 8, 0))
        self.assertEqual(db.page_size, 8192)
        self.assertEqual(db.locale, "ru_RU")
        self.assertEqual(db.tables[0].name, "T")
        self.assertEqual(db.tables[0].occupied, 1)
        self.assertEqual(db.tables[0].total, 2)
        self.assertEqual(db.tables[0].disk, 2 * 8192)

    def test_format_8214_is_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(
                path,
                [_simple()],
                version=(8, 2, 14, 0),
                locale="ru_RU",
                free_pages=3,
            )
            raw = path.read_bytes()
            self.assertEqual(raw[8:12], bytes((8, 2, 14, 0)))
            self.assertEqual(struct.unpack_from("<I", raw, 20)[0], 0)
            db = open_database(path)
        self.assertEqual(db.page_size, 4096)
        self.assertEqual(db.locale, "ru_RU")
        self.assertEqual(db.free_pages, 3)
        self.assertEqual(db.tables[0].occupied, 1)
        self.assertEqual(db.tables[0].disk, 3 * 4096)

    def test_format_805_short_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(path, [_simple("OLD")], version=(8, 0, 5, 0), locale="ru_RU")
            db = open_database(path)
        self.assertEqual(db.version, (8, 0, 5, 0))
        self.assertEqual(db.page_size, 4096)
        self.assertEqual(db.locale, "ru_RU")
        self.assertEqual(db.tables[0].name, "OLD")

    def test_fat1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(
                path,
                [_simple("FAT", flags=[1, 0, 0], fat=1)],
                version=(8, 3, 8, 0),
                page_size=4096,
            )
            db = open_database(path)
        table = db.tables[0]
        self.assertEqual(table.name, "FAT")
        self.assertEqual(table.occupied, 2)
        self.assertEqual(table.total, 3)
        self.assertEqual(table.disk, 3 * 4096)

    def test_long_description_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(path, [_simple("LONG", pad=800)], version=(8, 3, 8, 0), page_size=4096)
            db = open_database(path)
        self.assertEqual(db.tables[0].name, "LONG")
        self.assertEqual(db.tables[0].occupied, 1)

    def test_cp1251_bom_and_nul(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(
                path,
                [
                    {"name": "CP", "fields": [("Поле", "B", 0, 8)], "flags": [1, 0], "encoding": "cp1251"},
                    _simple("MARK", bom=True, nul=True),
                ],
                version=(8, 3, 8, 0),
                page_size=4096,
            )
            db = open_database(path)
        names = [table.name for table in db.tables]
        self.assertEqual(names, ["CP", "MARK"])

    def test_row_crosses_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(
                path,
                [{
                    "name": "WIDE",
                    "fields": [("_B", "B", 0, 3000)],
                    "flags": [1, 0, 1],
                }],
                version=(8, 3, 8, 0),
                page_size=4096,
            )
            db = open_database(path)
        table = db.tables[0]
        self.assertEqual(table.data, 3001 * 3)
        self.assertEqual(table.total, 3)
        self.assertEqual(table.occupied, 1)

    def test_sentinel_row_is_not_occupied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(path, [_simple(flags=[0, 0])], page_size=4096)
            db = open_database(path)
        self.assertEqual(db.tables[0].occupied, 1)
        self.assertEqual(db.tables[0].total, 2)

    def test_bad_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            path.write_bytes(b"NOT1CDB!" + b"\x00" * 64)
            with self.assertRaises(FormatError):
                open_database(path)

    def test_page_count_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(path, [_simple("KEEP")], page_size=4096)
            raw = bytearray(path.read_bytes())
            struct.pack_into("<I", raw, 12, 999)
            path.write_bytes(raw)
            db = open_database(path)
        self.assertTrue(any("страниц" in warning for warning in db.warnings))
        self.assertEqual(db.tables[0].name, "KEEP")
        self.assertEqual(db.tables[0].occupied, 1)

    def test_do_not_stop_fat_on_nonzero_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(path, [_simple()], version=(8, 3, 8, 0), page_size=8192)
            raw = bytearray(path.read_bytes())
            page = 8192
            target = None
            for offset in range(0, len(raw), page):
                if raw[offset:offset + 2] != b"\x1c\xfd":
                    continue
                length = struct.unpack_from("<Q", raw, offset + 16)[0]
                if length == 16:
                    target = offset
            self.assertIsNotNone(target)
            struct.pack_into("<I", raw, target + 28, 999)
            path.write_bytes(raw)
            db = open_database(path)
        self.assertEqual(db.tables[0].occupied, 1)
        self.assertEqual(db.tables[0].disk, 2 * 8192)

    def test_unknown_type_and_schema_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.1CD"
            write_database(
                path,
                [
                    {"name": "BAD", "description": "{обрыв", "data": b"\x00" * 16},
                    {"name": "WEIRD", "fields": [("_A", "ZZ", 0, 4)], "data": b"\x00" * 20},
                    _simple("GOOD"),
                ],
                page_size=4096,
            )
            db = open_database(path)
        names = [table.name for table in db.tables]
        self.assertIn("GOOD", names)
        self.assertNotIn("BAD", names)
        weird = next(table for table in db.tables if table.name == "WEIRD")
        self.assertIsNone(weird.occupied)
        self.assertEqual(weird.data, 20)
        self.assertTrue(db.warnings)
        self.assertEqual(next(table for table in db.tables if table.name == "GOOD").occupied, 1)

    def test_directory_without_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FormatError) as caught:
                open_database(tmp)
        self.assertIn("нет файла 1Cv8.1CD", str(caught.exception))

    def test_mini_example(self):
        self.assertTrue(MINI.is_file(), "examples/mini.1CD не собран")
        db = open_database(MINI)
        self.assertEqual(db.version, (8, 3, 8, 0))
        self.assertEqual(db.page_size, 8192)
        self.assertEqual(db.locale, "ru_RU")
        self.assertEqual(db.page_count, 22)
        self.assertEqual(db.file_size, 22 * 8192)
        self.assertEqual(db.free_pages, 2)
        self.assertEqual(format_size(db.file_size), "176 КБ")
        by_name = {table.name: table for table in db.tables}
        self.assertEqual(set(by_name), {"IBVERSION", "_Reference7", "_Reference7_VT3", "_AccumRg3"})
        ib = by_name["IBVERSION"]
        ref = by_name["_Reference7"]
        vt = by_name["_Reference7_VT3"]
        acc = by_name["_AccumRg3"]
        self.assertEqual((ib.occupied, ib.total), (1, 2))
        self.assertEqual(ib.purpose, "версия ИБ")
        self.assertEqual((ref.occupied, ref.total), (2, 4))
        self.assertEqual(ref.purpose, "справочник")
        self.assertEqual((ref.data, ref.blob, ref.index, ref.stream, ref.disk), (256, 512, 100, 868, 48 * 1024))
        self.assertEqual((vt.occupied, vt.total), (1, 2))
        self.assertEqual(vt.purpose, "табличная часть")
        self.assertEqual((acc.occupied, acc.total), (20, 21))
        self.assertEqual(acc.purpose, "регистр накопления")
        self.assertEqual((acc.data, acc.blob, acc.index), (672, 64, 4096))
        self.assertEqual(acc.stream, 672 + 64 + 4096)
        self.assertEqual(acc.disk, 48 * 1024)
        self.assertEqual(format_size(acc.index), "4 КБ")
        self.assertEqual(format_size(acc.stream), "4.7 КБ")
        self.assertEqual(format_size(ref.stream), "868 Б")
        self.assertEqual(format_size(ref.disk), "48 КБ")
        occupied = sum(table.occupied for table in db.tables)
        total = sum(table.total for table in db.tables)
        stream = sum(table.stream for table in db.tables)
        disk = sum(table.disk for table in db.tables)
        self.assertEqual((occupied, total), (24, 29))
        self.assertEqual(format_size(stream), "5.7 КБ")
        self.assertEqual(format_size(disk), "144 КБ")
        text = render_text(db)
        self.assertIn("свободно: 2", text)
        self.assertIn("_Reference7", text)
        self.assertNotEqual(db.free_pages, sum(
            (table.total or 0) - (table.occupied or 0) for table in db.tables
        ))

    def test_build_mini_matches_example_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_mini(Path(tmp) / "mini.1CD")
            fresh = open_database(path)
            saved = open_database(MINI)
        self.assertEqual(fresh.file_size, saved.file_size)
        self.assertEqual(
            [(table.name, table.stream, table.disk, table.occupied, table.total) for table in fresh.tables],
            [(table.name, table.stream, table.disk, table.occupied, table.total) for table in saved.tables],
        )


if __name__ == "__main__":
    unittest.main()
