import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from merge_purge.cli import main
from merge_purge.engine import DROP_COLUMNS, MAIL_COLUMNS, SUMMARY_COLUMNS, merge
from merge_purge.workbook import InputError, SCHEMAS, read_input, write_output
from tests.test_rules import record


def fixture(path):
    book = Workbook()
    book.remove(book.active)
    data = {
        "Plan": [("A", "Outside", 1, "Alpha", "All")],
        "Records": [tuple(record(1)[c] for c in SCHEMAS["Records"])],
        "Nicknames": [("BOB", "ROBERT")],
        "StreetSuffixes": [("STREET", "ST")],
    }
    for title, columns in SCHEMAS.items():
        sheet = book.create_sheet(title)
        sheet.append(columns)
        for row in data[title]:
            sheet.append(row)
    book.save(path)
    book.close()


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "input.xlsx"
        self.output = Path(self.directory.name) / "output.xlsx"
        fixture(self.source)

    def modify(self, action):
        book = load_workbook(self.source)
        action(book)
        book.save(self.source)
        book.close()

    def test_roundtrip_exact_sheets_and_headers(self):
        result = merge(*read_input(self.source))
        write_output(self.output, result)
        book = load_workbook(self.output)
        try:
            self.assertEqual(book.sheetnames, ["Mail", "Drops", "Summary"])
            for title, columns in [("Mail", MAIL_COLUMNS), ("Drops", DROP_COLUMNS), ("Summary", SUMMARY_COLUMNS)]:
                self.assertEqual(tuple(c.value for c in book[title][1]), columns)
            self.assertEqual(book["Mail"]["J2"].value, "02134")
            self.assertEqual(book["Mail"]["J2"].data_type, "s")
        finally:
            book.close()

    def test_text_cannot_become_an_output_formula(self):
        def change(book):
            cell = book["Records"].cell(2, 9, '=HYPERLINK("https://example.invalid","x")')
            cell.data_type = "s"
        self.modify(change)
        result = merge(*read_input(self.source))
        write_output(self.output, result)
        book = load_workbook(self.output, data_only=False)
        try:
            self.assertEqual(book["Mail"]["H2"].data_type, "s")
            self.assertTrue(book["Mail"]["H2"].value.startswith("=HYPERLINK"))
        finally:
            book.close()

    def test_formula_input_is_not_silently_treated_as_blank(self):
        self.modify(lambda w: w["Records"].cell(2, 11, "=2000+134"))
        with self.assertRaisesRegex(InputError, "formulas"):
            read_input(self.source)

    def test_missing_sheet(self):
        self.modify(lambda w: w.remove(w["Plan"]))
        with self.assertRaisesRegex(InputError, "Missing sheet"):
            read_input(self.source)

    def test_missing_column(self):
        self.modify(lambda w: w["Records"].cell(1, 1, "WRONG"))
        with self.assertRaisesRegex(InputError, "column headers"):
            read_input(self.source)

    def test_unknown_key(self):
        self.modify(lambda w: w["Records"].cell(2, 2, "UNKNOWN"))
        with self.assertRaisesRegex(InputError, "not in Plan"):
            read_input(self.source)

    def test_duplicate_id(self):
        self.modify(lambda w: w["Records"].append([c.value for c in w["Records"][2]]))
        with self.assertRaisesRegex(InputError, "unique integer"):
            read_input(self.source)

    def test_invalid_priority(self):
        self.modify(lambda w: w["Plan"].cell(2, 3, "high"))
        with self.assertRaisesRegex(InputError, "PRIORITY"):
            read_input(self.source)

    def test_conflicting_lookup(self):
        self.modify(lambda w: w["Nicknames"].append(["BOB", "BOBBY"]))
        with self.assertRaisesRegex(InputError, "conflicting"):
            read_input(self.source)

    def test_cli_errors_preserve_source_and_output(self):
        original = self.source.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.source), str(self.source), "--force"]), 1)
        self.assertEqual(self.source.read_bytes(), original)
        self.output.write_bytes(b"existing")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.source), str(self.output)]), 1)
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_cli_success_and_force(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.source), str(self.output)]), 0)
            self.assertEqual(main([str(self.source), str(self.output), "--force"]), 0)

    def test_failed_save_preserves_existing_output_and_removes_temp_file(self):
        result = merge(*read_input(self.source))
        self.output.write_bytes(b"existing output")
        before = set(self.output.parent.iterdir())
        with patch("merge_purge.workbook.Workbook.save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                write_output(self.output, result)
        self.assertEqual(self.output.read_bytes(), b"existing output")
        self.assertEqual(set(self.output.parent.iterdir()), before)

    def test_corrupt_input_has_clean_error(self):
        self.source.write_bytes(b"not an xlsx")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main([str(self.source), str(self.output)]), 1)
        self.assertTrue(errors.getvalue().startswith("Error:"))
        self.assertFalse(self.output.exists())


class SuppliedWorkbookTests(unittest.TestCase):
    def test_expected_summary_and_specific_decisions(self):
        source = Path(__file__).resolve().parents[1] / "merge_test_input.xlsx"
        result = merge(*read_input(source))
        self.assertEqual(result.summary, [
            ("H01", 23, 0, 0, 0, 0, 23, 0),
            ("H02", 23, 0, 1, 0, 0, 22, 0),
            ("O01", 39, 1, 1, 5, 0, 32, 4),
            ("O02", 38, 1, 1, 4, 0, 32, 5),
            ("O03", 33, 1, 0, 8, 1, 23, 0),
            ("TOTAL", 156, 3, 3, 17, 1, 132, 9),
        ])
        drops = {r[0]: r[2:] for r in result.drops}
        for rec_id in [100059, 100090, 100130]:
            self.assertEqual(drops[rec_id], ("REJECT", None))
        for rec_id in [100025, 100103, 100068]:
            self.assertEqual(drops[rec_id], ("SUPPRESS", None))
        self.assertEqual(drops[100113], ("DUP_INTRA", 100037))
        self.assertEqual(drops[100003], ("DUP_INTER", 100064))
        self.assertEqual(drops[100141], ("DUP_INTER", 100064))
        self.assertEqual(drops[100118], ("DUP_INTER", 100032))
        mail = {r[0]: r for r in result.mail}
        self.assertEqual(mail[100064][-1], 3)
        self.assertEqual(mail[100032][-1], 2)
        self.assertIn(100056, mail)  # Reed SR and JR are separate, with no blank bridge.
        self.assertIn(100112, mail)
        self.assertIn(100124, mail)  # Nina Shaw: known unit differs from missing unit.
        self.assertIn(100161, mail)
        ids = [r[0] for r in result.mail] + [r[0] for r in result.drops]
        self.assertEqual(len(ids), 156)
        self.assertEqual(len(set(ids)), 156)


if __name__ == "__main__":
    unittest.main()
