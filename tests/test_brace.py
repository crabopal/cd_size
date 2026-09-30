import unittest

from cdsize.brace import BraceError, parse_brace


class BraceTests(unittest.TestCase):
    def test_nested_lists_and_numbers(self):
        self.assertEqual(parse_brace("{1,2,{3,4}}"), [1, 2, [3, 4]])

    def test_doubled_quotes(self):
        self.assertEqual(parse_brace('{"Строка ""2"""}'), ['Строка "2"'])

    def test_empty_values(self):
        self.assertEqual(parse_brace("{1,,3}"), [1, None, 3])

    def test_atom(self):
        value = parse_brace("{2,e5c73637-e8d6-47e0-9c15-2fa1802ee5b0}")
        self.assertEqual(value[0], 2)
        self.assertEqual(value[1], "e5c73637-e8d6-47e0-9c15-2fa1802ee5b0")

    def test_unclosed(self):
        with self.assertRaises(BraceError):
            parse_brace("{1,2")
