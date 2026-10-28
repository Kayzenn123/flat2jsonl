#!/usr/bin/env python3
"""Tests for flat2jsonl — run: python3 -m unittest discover -s test -q"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flat2jsonl  # noqa: E402

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "flat2jsonl.py")


def run_text(csv_text, *args):
    """Convert an in-memory CSV string; returns (rows, stderr)."""
    opts = flat2jsonl.build_parser().parse_args(list(args))
    out = io.StringIO()
    err = io.StringIO()
    old_err = sys.stderr
    sys.stderr = err
    try:
        flat2jsonl.convert_stream(io.StringIO(csv_text), out, opts, "test")
    finally:
        sys.stderr = old_err
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    return rows, err.getvalue()


class TestBasic(unittest.TestCase):
    def test_flat_rows(self):
        rows, _ = run_text("name,age,city\nAna,20,Jakarta\nBudi,31,Bandung\n")
        self.assertEqual(rows, [
            {"name": "Ana", "age": 20, "city": "Jakarta"},
            {"name": "Budi", "age": 31, "city": "Bandung"},
        ])

    def test_type_inference(self):
        rows, _ = run_text(
            "item,price,stock,active,note\n"
            "kopi,15000.5,3,true,ok\n"
            "gula,9000,0,false,null\n"
        )
        self.assertEqual(rows[0]["price"], 15000.5)
        self.assertEqual(rows[0]["stock"], 3)
        self.assertIs(rows[0]["active"], True)
        self.assertIs(rows[1]["active"], False)
        self.assertIsNone(rows[1]["note"])
        self.assertIsInstance(rows[0]["price"], float)

    def test_leading_zero_stays_string(self):
        rows, _ = run_text("code,phone\n007,081234567890\n")
        self.assertEqual(rows[0]["code"], "007")
        self.assertEqual(rows[0]["phone"], "081234567890")
        self.assertIsInstance(rows[0]["code"], str)

    def test_no_infer_keeps_strings(self):
        rows, _ = run_text("a,b\n42,true\n", "--no-infer")
        self.assertEqual(rows[0], {"a": "42", "b": "true"})

    def test_quoted_commas_and_multiline(self):
        rows, _ = run_text(
            'title,desc\n"Hello, world","line1\nline2"\n'
        )
        self.assertEqual(rows[0]["title"], "Hello, world")
        self.assertEqual(rows[0]["desc"], "line1\nline2")


class TestNest(unittest.TestCase):
    def test_nested_keys(self):
        rows, _ = run_text(
            "user.name,user.age,user.city\nAna,20,Jakarta\n", "--nest"
        )
        self.assertEqual(rows[0], {
            "user": {"name": "Ana", "age": 20, "city": "Jakarta"},
        })

    def test_nest_conflict_errors(self):
        with self.assertRaises(flat2jsonl.FlatError):
            run_text("a,a.b\n1,2\n", "--nest")

    def test_nest_bad_key_errors(self):
        with self.assertRaises(flat2jsonl.FlatError):
            run_text("a..b\n1\n", "--nest")


class TestDelimiter(unittest.TestCase):
    def test_semicolon_sniffed(self):
        rows, _ = run_text("a;b;c\n1;2;3\n")
        self.assertEqual(rows[0], {"a": 1, "b": 2, "c": 3})

    def test_tab_sniffed(self):
        rows, _ = run_text("a\tb\n1\t2\n")
        self.assertEqual(rows[0], {"a": 1, "b": 2})

    def test_explicit_delimiter_wins(self):
        rows, _ = run_text("a|b\n1|2\n", "--delimiter", "|")
        self.assertEqual(rows[0], {"a": 1, "b": 2})


class TestErrors(unittest.TestCase):
    def test_empty_input_errors(self):
        with self.assertRaises(flat2jsonl.FlatError):
            run_text("")

    def test_header_only_is_ok(self):
        rows, _ = run_text("a,b\n")
        self.assertEqual(rows, [])

    def test_duplicate_header_errors(self):
        with self.assertRaises(flat2jsonl.FlatError):
            run_text("a,a\n1,2\n")

    def test_short_row_errors(self):
        with self.assertRaises(flat2jsonl.FlatError):
            run_text("a,b,c\n1,2\n")

    def test_skip_bad_continues(self):
        rows, err = run_text("a,b\n1,2\n3\n4,5\n", "--skip-bad")
        self.assertEqual(rows, [{"a": 1, "b": 2}, {"a": 4, "b": 5}])
        self.assertIn("warning", err)

    def test_columns_subset_and_order(self):
        rows, _ = run_text("a,b,c\n1,2,3\n", "--columns", "c,a")
        self.assertEqual(rows[0], {"c": 3, "a": 1})

    def test_unknown_column_errors(self):
        with self.assertRaises(flat2jsonl.FlatError):
            run_text("a,b\n1,2\n", "--columns", "a,zz")

    def test_bom_stripped(self):
        rows, _ = run_text("\ufeffa,b\n1,2\n")
        self.assertEqual(rows[0], {"a": 1, "b": 2})


class TestCliEndToEnd(unittest.TestCase):
    def test_cli_stdin_and_exit_code(self):
        proc = subprocess.run(
            [sys.executable, BIN],
            input="name,score\nAna,95\nBudi,80\n",
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")
        rows = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(rows, [
            {"name": "Ana", "score": 95},
            {"name": "Budi", "score": 80},
        ])

    def test_cli_file_and_bad_flag(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False) as tmp:
            tmp.write("x,y\n1,2\n")
            path = tmp.name
        try:
            proc = subprocess.run(
                [sys.executable, BIN, path],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout), {"x": 1, "y": 2})
            bad = subprocess.run(
                [sys.executable, BIN, "--nope"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(bad.returncode, 2)
            missing = subprocess.run(
                [sys.executable, BIN, "/definitely/not/here.csv"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(missing.returncode, 1)
            self.assertIn("error", missing.stderr)
        finally:
            os.unlink(path)

    def test_cli_version_and_help(self):
        ver = subprocess.run(
            [sys.executable, BIN, "--version"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(ver.returncode, 0)
        self.assertIn("flat2jsonl 1.0.0", ver.stdout)
        help_out = subprocess.run(
            [sys.executable, BIN, "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(help_out.returncode, 0)
        self.assertIn("--nest", help_out.stdout)


if __name__ == "__main__":
    unittest.main()
