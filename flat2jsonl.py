#!/usr/bin/env python3
"""flat2jsonl — convert flat CSV to JSON Lines, streaming.

Reads CSV rows one at a time and writes one JSON object per line to
stdout. Memory usage stays constant no matter how large the input is.

Features:
  * delimiter auto-detection (comma, semicolon, tab, pipe) with override
  * type inference: int, float, bool, null (leading-zero strings stay text)
  * --nest: dotted headers (user.name) become nested objects
  * BOM stripping, --encoding, --columns subset, --skip-bad rows
  * reads files or stdin, writes stdout, errors to stderr

Exit codes: 0 ok, 1 runtime error, 2 argument error.
"""

import argparse
import csv
import itertools
import json
import re
import sys

VERSION = "1.0.0"

DELIMITERS = [",", ";", "\t", "|"]
SAMPLE_LINES = 5
SAMPLE_BYTES = 8192

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)[eE][+-]?\d+$|^[+-]?\d*\.\d+$")


class FlatError(Exception):
    """Runtime error with a user-facing message (exit code 1)."""


def infer_value(raw):
    """Convert one raw CSV cell to a JSON value.

    Empty, 'null' and 'none' (any case) become None. 'true'/'false'
    become booleans. Integers and floats are parsed, except strings
    with leading zeros ('007', '0812') which stay strings so codes
    and phone numbers survive. Everything else stays a string.
    """
    text = raw.strip()
    if text == "" or text.lower() in ("null", "none"):
        return None
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT_RE.match(text):
        digits = text.lstrip("+-")
        if len(digits) > 1 and digits.startswith("0"):
            return raw
        try:
            return int(text)
        except ValueError:
            return raw
    if _FLOAT_RE.match(text):
        try:
            value = float(text)
        except ValueError:
            return raw
        if value != value or value in (float("inf"), float("-inf")):
            return raw
        return value
    return raw


def nest_row(pairs):
    """Build a (possibly nested) dict from (dotted-key, value) pairs.

    Raises FlatError on conflicting keys, e.g. both 'a' and 'a.b'.
    """
    out = {}
    for key, value in pairs:
        parts = key.split(".")
        if any(p == "" for p in parts):
            raise FlatError(f"invalid header key {key!r}: empty segment")
        node = out
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                child = {}
                node[part] = child
            elif not isinstance(child, dict):
                raise FlatError(
                    f"conflicting keys: {key!r} collides with a plain value"
                )
            node = child
        leaf = parts[-1]
        if leaf in node:
            raise FlatError(f"conflicting keys: {key!r} appears twice")
        node[leaf] = value
    return out


def detect_delimiter(sample_lines):
    """Guess the delimiter from sample lines, defaulting to comma."""
    sample = "".join(sample_lines)
    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(DELIMITERS))
        if dialect.delimiter in DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass
    return ","


def convert_stream(stream, out, opts, source_name):
    """Convert one CSV text stream to JSONL. Returns rows written."""
    sample = []
    while len(sample) < SAMPLE_LINES:
        try:
            line = next(stream)
        except StopIteration:
            break
        sample.append(line)
        if sum(len(s) for s in sample) >= SAMPLE_BYTES:
            break
    if not sample:
        raise FlatError(f"{source_name}: empty input, no header row")

    delimiter = opts.delimiter or detect_delimiter(sample)
    rows = itertools.chain(sample, stream)
    reader = csv.reader(rows, delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise FlatError(f"{source_name}: empty input, no header row")
    header = [h.strip() for h in header]
    if header:
        header[0] = header[0].lstrip("\ufeff")
    if not header or all(h == "" for h in header):
        raise FlatError(f"{source_name}: header row is empty")
    dupes = {h for h in header if header.count(h) > 1}
    if dupes:
        raise FlatError(
            f"{source_name}: duplicate column name(s): {', '.join(sorted(dupes))}"
        )

    columns = opts.columns
    if isinstance(columns, str):
        columns = [c.strip() for c in columns.split(",") if c.strip()]
    full_header = header
    if columns:
        missing = [c for c in columns if c not in header]
        if missing:
            raise FlatError(
                f"unknown column(s): {', '.join(missing)} "
                f"(available: {', '.join(header)})"
            )
        keep = [header.index(c) for c in columns]
        header = [header[i] for i in keep]
    else:
        keep = None

    written = 0
    for row in reader:
        if not row:
            continue
        if len(row) != len(full_header):
            if opts.skip_bad:
                print(
                    f"flat2jsonl: warning: {source_name} line "
                    f"{reader.line_num}: expected "
                    f"{len(full_header)} columns, "
                    f"got {len(row)}; skipped",
                    file=sys.stderr,
                )
                continue
            raise FlatError(
                f"{source_name} line {reader.line_num}: expected "
                f"{len(full_header)} columns, got {len(row)}"
            )
        if keep is not None:
            row = [row[i] for i in keep]
        values = [
            raw if opts.no_infer else infer_value(raw) for raw in row
        ]
        try:
            obj = (
                nest_row(zip(header, values))
                if opts.nest
                else dict(zip(header, values))
            )
        except FlatError as exc:
            if opts.skip_bad:
                print(
                    f"flat2jsonl: warning: {source_name} line "
                    f"{reader.line_num}: {exc}; skipped",
                    file=sys.stderr,
                )
                continue
            raise FlatError(f"{source_name} line {reader.line_num}: {exc}")
        out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        written += 1
    return written


def open_input(path, encoding):
    """Open a CSV file (or stdin for '-') as a text stream."""
    if path == "-":
        sys.stdin.reconfigure(encoding=encoding, errors="replace")
        return sys.stdin
    return open(path, "r", encoding=encoding, errors="replace", newline="")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="flat2jsonl",
        description=(
            "Convert flat CSV to JSON Lines, streaming: one CSV row in, "
            "one JSON object out. Reads files or stdin, writes stdout."
        ),
    )
    parser.add_argument(
        "files", nargs="*", metavar="FILE",
        help="CSV file(s) to convert; omit to read stdin ('-' also stdin)",
    )
    parser.add_argument(
        "--delimiter", metavar="C",
        help="column separator (default: auto-detect , ; TAB |)",
    )
    parser.add_argument(
        "--encoding", default="utf-8-sig", metavar="ENC",
        help="input encoding (default: utf-8-sig, strips UTF-8 BOM)",
    )
    parser.add_argument(
        "--nest", action="store_true",
        help="turn dotted headers (user.name) into nested objects",
    )
    parser.add_argument(
        "--no-infer", action="store_true",
        help="keep every value a string (no int/float/bool/null inference)",
    )
    parser.add_argument(
        "--columns", metavar="A,B",
        help="only output these columns, in this order",
    )
    parser.add_argument(
        "--skip-bad", action="store_true",
        help="skip malformed rows with a warning instead of stopping",
    )
    parser.add_argument(
        "--version", action="version", version=f"flat2jsonl {VERSION}",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    opts = parser.parse_args(argv)
    if opts.delimiter is not None and len(opts.delimiter) != 1:
        parser.error("--delimiter must be a single character")
    if opts.columns:
        opts.columns = [c.strip() for c in opts.columns.split(",") if c.strip()]
        if not opts.columns:
            parser.error("--columns needs at least one column name")

    sources = opts.files if opts.files else ["-"]
    try:
        for path in sources:
            try:
                stream = open_input(path, opts.encoding)
            except OSError as exc:
                raise FlatError(f"cannot open {path}: {exc.strerror or exc}")
            except LookupError:
                raise FlatError(f"unknown encoding: {opts.encoding}")
            try:
                if path == "-":
                    convert_stream(stream, sys.stdout, opts, "<stdin>")
                else:
                    with stream:
                        convert_stream(stream, sys.stdout, opts, path)
            except UnicodeDecodeError as exc:
                raise FlatError(f"{path}: decode error: {exc}")
    except FlatError as exc:
        print(f"flat2jsonl: error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
