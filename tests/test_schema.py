import unittest

from cdsize.schema import (
    choose_row_size,
    field_width,
    kind_of,
    parse_table,
    row_size_candidates,
)

REFERENCE4 = """
{"_Reference4",0,
{"Fields",
{"_IDRREF","B",0,16,0,"CS"},
{"_VERSION","RV",0,0,0,"CS"},
{"_MARKED","L",0,0,0,"CS"},
{"_ISMETADATA","L",0,0,0,"CS"},
{"_CODE","NC",0,9,0,"CI"},
{"_DESCRIPTION","NVC",0,25,0,"CI"},
{"_FLD7","I",1,0,0,"CS"}
},
{"Indexes",
{"_IDRREFIDX",1,
{"_IDRREF",16}
},
{"_REFERENCE4_CODE_SR",0,
{"_CODE",9},
{"_IDRREF",16}
},
{"_REFERENCE4_DESCR_SR",0,
{"_DESCRIPTION",25},
{"_IDRREF",16}
}
},
{"Recordlock","0"},
{"Files",118,119,96}
}
"""


class SchemaTests(unittest.TestCase):
    def test_reference4_width(self):
        table = parse_table(REFERENCE4)
        self.assertEqual(table.name, "_Reference4")
        self.assertEqual(table.data_page, 118)
        self.assertEqual(table.blob_page, 119)
        self.assertEqual(table.index_page, 96)
        self.assertFalse(table.recordlock)
        sizes = row_size_candidates(table.fields, table.recordlock)
        self.assertEqual(sizes, [114])

    def test_field_widths(self):
        self.assertEqual(field_width("N", 5, False), (5 + 2) // 2)
        self.assertEqual(field_width("N", 10, True), 1 + (10 + 2) // 2)
        self.assertEqual(field_width("NC", 9, False), 18)
        self.assertEqual(field_width("NVC", 25, False), 52)
        self.assertEqual(field_width("I", 0, True), 9)
        self.assertEqual(field_width("DT", 0, False), 7)
        self.assertEqual(field_width("RV", 0, False), 16)
        self.assertIsNone(field_width("ZZ", 4, False))

    def test_recordlock_candidates(self):
        from cdsize.schema import Field

        fields = [Field("_PERIOD", "DT", False, 0), Field("_RECORDER", "B", False, 16)]
        self.assertEqual(row_size_candidates(fields, True), [32, 24])
        self.assertEqual(choose_row_size([32, 24], 672), 32)
        self.assertEqual(choose_row_size([32, 24], 24), 24)
        self.assertEqual(choose_row_size([32, 24], 0), 32)
        self.assertEqual(row_size_candidates([Field("_F", "L", False, 0)], False), [5])

    def test_kind(self):
        self.assertEqual(kind_of("_Reference7"), "справочник")
        self.assertEqual(kind_of("_Reference7_VT3"), "табличная часть")
        self.assertEqual(kind_of("_AccumRg3"), "регистр накопления")
        self.assertEqual(kind_of("_AccumRgT12"), "итоги")
        self.assertEqual(kind_of("_AccumRgOpt"), "настройки регистра накопления")
        self.assertEqual(kind_of("CONFIG"), "конфигурация")
        self.assertEqual(kind_of("PARAMS"), "параметры")
        self.assertEqual(kind_of("V8USERS"), "пользователи")
        self.assertEqual(kind_of("IBVERSION"), "версия ИБ")
        self.assertEqual(kind_of("DBSCHEMA"), "схема базы")
        self.assertEqual(kind_of("FILES"), "файлы")
        self.assertEqual(kind_of("_InfoRg1"), "регистр сведений")
        self.assertEqual(kind_of("_Document10"), "документ")
