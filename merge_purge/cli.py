"""CLI orchestration; computation stays separate from file handling."""

import argparse
import sys
from pathlib import Path
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from openpyxl.utils.exceptions import InvalidFileException

from .engine import merge
from .workbook import InputError, read_input, write_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge/purge mailing lists using the assessment's exact rules.")
    parser.add_argument("input", type=Path, help="Source .xlsx containing the four required sheets")
    parser.add_argument("output", type=Path, help="Destination .xlsx with Mail, Drops, Summary")
    parser.add_argument("--force", action="store_true", help="Replace an existing output workbook")
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise InputError("Input and output must be different files.")
        if args.output.suffix.lower() != ".xlsx":
            raise InputError("Output must have an .xlsx extension.")
        if args.output.exists() and not args.force:
            raise InputError("Output already exists. Use --force to replace it.")
        result = merge(*read_input(args.input))
        write_output(args.output, result)
    except (InputError, OSError, BadZipFile, InvalidFileException, ParseError,
            DefusedXmlException, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.output}: {len(result.mail)} mailed, {len(result.drops)} dropped.")
    return 0
