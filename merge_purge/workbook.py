"""Validated XLSX input and atomic, formula-safe output."""

import math
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from .engine import DROP_COLUMNS, MAIL_COLUMNS, SUMMARY_COLUMNS, Result
from .normalization import name, text

RECORD_COLUMNS = ("REC_ID", "KEY_CODE", "CUSTOMER_ID", "FIRST_NAME", "LAST_NAME", "SUFFIX",
                  "ADDRESS_1", "ADDRESS_2", "CITY", "STATE", "ZIP", "EMAIL", "PHONE", "GENDER",
                  "LAST_ORDER_DATE", "ORDER_TOTAL")
SCHEMAS = {
    "Plan": ("KEY_CODE", "TYPE", "PRIORITY", "LIST", "SEGMENT"),
    "Records": RECORD_COLUMNS,
    "Nicknames": ("NICKNAME", "FULL_NAME"),
    "StreetSuffixes": ("WORD", "STANDARD"),
}


class InputError(ValueError):
    """The workbook structure is invalid; distinct from a rejected mail record."""


def read_input(path: Path) -> tuple:
    if path.suffix.lower() != ".xlsx":
        raise InputError("Input must be an .xlsx workbook.")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise InputError("Input exceeds the 50 MiB file limit.")
    with ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
            raise InputError("Workbook exceeds the 100 MiB uncompressed limit.")
    book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        tables = {}
        for sheet, required in SCHEMAS.items():
            if sheet not in book.sheetnames:
                raise InputError(f"Missing sheet: {sheet}")
            rows = book[sheet].iter_rows()
            header = tuple(c.value for c in next(rows, ()))
            if len(set(header)) != len(header) or not set(required).issubset(header):
                raise InputError(f"{sheet}: missing or duplicate column headers.")
            table = []
            for number, cells in enumerate(rows, 2):
                if all(c.value is None for c in cells):
                    continue
                if any(c.data_type in {"f", "e"} for c in cells):
                    raise InputError(f"{sheet} row {number}: formulas and Excel errors are unsupported.")
                table.append(dict(zip(header, (c.value for c in cells))))
            tables[sheet] = table

        plan = tables["Plan"]
        files = {}
        for row in plan:
            key, kind = row["KEY_CODE"], row["TYPE"]
            if not isinstance(key, str) or not key.strip() or key == "TOTAL" or key in files:
                raise InputError("Plan KEY_CODE must be unique, non-empty text and not TOTAL.")
            if kind not in {"House", "Outside", "Suppress"}:
                raise InputError(f"Plan {key}: TYPE must be House, Outside or Suppress.")
            priority = row["PRIORITY"]
            if kind != "Suppress" and (isinstance(priority, bool) or not isinstance(priority, (int, float))
                                       or not math.isfinite(priority)):
                raise InputError(f"Plan {key}: mail PRIORITY must be a finite number.")
            if kind == "Outside" and not text(row["LIST"]).strip():
                raise InputError(f"Plan {key}: Outside LIST must be non-empty.")
            files[key] = row
        seen = set()
        for row in tables["Records"]:
            rec_id = row["REC_ID"]
            if isinstance(rec_id, bool) or not isinstance(rec_id, (int, float)):
                raise InputError("REC_ID must be a unique integer.")
            if not math.isfinite(rec_id) or int(rec_id) != rec_id or rec_id in seen:
                raise InputError("REC_ID must be a unique integer.")
            row["REC_ID"] = int(rec_id)
            seen.add(rec_id)
            if row["KEY_CODE"] not in files:
                raise InputError(f"REC_ID {rec_id}: KEY_CODE is not in Plan.")

        def mapping(sheet: str, source: str, target: str, clean) -> dict:
            result = {}
            for row in tables[sheet]:
                key, value = clean(row[source]), clean(row[target])
                if not key or not value or (key in result and result[key] != value):
                    raise InputError(f"{sheet}: empty or conflicting lookup entry.")
                result[key] = value
            return result

        nicknames = mapping("Nicknames", "NICKNAME", "FULL_NAME", name)
        suffixes = mapping("StreetSuffixes", "WORD", "STANDARD", lambda v: text(v).strip().upper())
        return plan, tables["Records"], nicknames, suffixes
    finally:
        book.close()


def write_output(path: Path, result: Result) -> None:
    """Save to a sibling temporary file, then replace only after a successful save."""
    book = Workbook()
    book.remove(book.active)
    for title, columns, rows in (("Mail", MAIL_COLUMNS, result.mail),
                                  ("Drops", DROP_COLUMNS, result.drops),
                                  ("Summary", SUMMARY_COLUMNS, result.summary)):
        sheet = book.create_sheet(title)
        sheet.append(columns)
        for row in rows:
            sheet.append(row)
        for row in sheet:
            for cell in row:
                # Preserve exact input text without allowing it to become a formula.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="173E52")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in column)
            sheet.column_dimensions[column[0].column_letter].width = min(45, max(12, width + 2))
    fd, temporary = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(fd)
    try:
        book.save(temporary)
        os.replace(temporary, path)
    finally:
        book.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
