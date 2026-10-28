# flat2jsonl

> Convert flat CSV to JSON Lines, streaming — one row in, one JSON object out. Daily Tools #22.

## Why

Export CSV files are everywhere (sales dumps, public datasets, scraped
tables), and JSON Lines is what `jq`, log pipelines, and database bulk
importers actually want. The closest single-file alternative,
`jruere/csv2jsonl`, converts plainly but has no type inference, no
nested objects, no delimiter detection, and no way to pick columns or
skip bad rows. The heavyweight option,
`Siddharth-lal-13/universal-json-converter`, handles many formats but
needs dependency installs. flat2jsonl is one Python file, zero
dependencies, and streams: a 100,000-row file converts with ~13 MB max
RSS, so it works on multi-hundred-megabyte exports and on Termux.

## Install

```bash
git clone https://github.com/Kayzenn123/flat2jsonl.git
cd flat2jsonl
# no dependencies — Python 3.9+ standard library only
```

Requires: Python >= 3.9

## Usage

```bash
python3 flat2jsonl.py sales.csv > sales.jsonl
cat sales.csv | python3 flat2jsonl.py --nest > nested.jsonl
python3 flat2jsonl.py --delimiter ';' --columns name,total big.csv
python3 flat2jsonl.py --help
```

| Flag | Function | Default |
| --- | --- | --- |
| `[FILE ...]` | CSV file(s); omit to read stdin | stdin |
| `--delimiter C` | Column separator | auto-detect `,` `;` TAB `\|` |
| `--encoding ENC` | Input encoding | `utf-8-sig` (strips UTF-8 BOM) |
| `--nest` | Dotted headers become nested objects | off |
| `--no-infer` | Keep every value a string | off (infer int/float/bool/null) |
| `--columns A,B` | Only output these columns, in this order | all columns |
| `--skip-bad` | Skip malformed rows with a warning | stop on first bad row |
| `--version` | Print version | — |

Exit codes: `0` success, `1` runtime error (missing file, malformed
CSV, duplicate header), `2` argument error.

## Example output

Command:

```bash
python3 flat2jsonl.py examples/sales.csv
```

Output (real, copied from an actual run):

```text
{"order_id": 1001, "product": "kopi tubruk", "price": 15000, "qty": 2, "paid": true}
{"order_id": 1002, "product": "gula aren", "price": 22000.5, "qty": 1, "paid": true}
{"order_id": 1003, "product": "teh melati", "price": 12000, "qty": 3, "paid": false}
```

Nested mode:

```bash
python3 flat2jsonl.py --nest examples/nested.csv
```

```text
{"customer": {"name": "Ana", "city": "Jakarta"}, "order": {"total": 30000, "paid": true}}
{"customer": {"name": "Budi", "city": "Bandung"}, "order": {"total": 22000.5, "paid": false}}
```

Large-file streaming (100,000 rows, 3.1 MB, semicolon-delimited):

```bash
python3 flat2jsonl.py /tmp/big-orders.csv | wc -l
```

```text
100000
```

Max RSS for that conversion was 12,956 KB (measured with
`resource.getrusage`), i.e. memory stays flat while the file grows.

## How it works

1. The first up-to-5 lines are read as a sample; `csv.Sniffer`
   detects the delimiter (`,`, `;`, TAB, `|`), then those lines are
   chained back into the stream — nothing is re-read or buffered.
2. Each row is converted one at a time: values are type-inferred
   (`15000` → int, `22000.5` → float, `true` → bool, empty/`null` →
   `null`), while leading-zero strings like `007` or `0812` stay
   strings so codes and phone numbers survive.
3. With `--nest`, dotted headers (`customer.name`) are folded into
   nested objects; key conflicts are reported with the line number.
4. Malformed rows (wrong column count) stop the run with the line
   number, unless `--skip-bad` is given.
5. Output is one JSON object per line (`ensure_ascii=False`, so
   Indonesian text stays readable), written to stdout; all messages
   go to stderr.

## Limitations

- One header row per file; headerless CSV is not supported.
- `--columns` names must match the header exactly (case-sensitive).
- Type inference is heuristic: `1e3` stays a string (no exponent
  form), and dates stay strings.
- Multi-file input treats each file as having its own header; a bad
  file stops the run after earlier files already printed.
- `--nest` rejects conflicting keys (`a` and `a.b` in one file).
- Quoted multi-line fields are supported, but the line number in
  error messages then counts physical lines.

## Development

```bash
python3 -m unittest discover -s test -q
```

## License

MIT

---
Ringkasan (Bahasa Indonesia): flat2jsonl mengubah CSV menjadi JSON
Lines secara streaming — satu baris CSV masuk, satu objek JSON keluar —
tanpa memuat seluruh file ke RAM (100.000 baris hanya butuh ~13 MB).
Fiturnya: deteksi pemisah otomatis, inferensi tipe (angka, boolean,
null), mode --nest untuk header bertitik, dan flag --columns/--skip-bad.
Satu file Python tanpa dependensi; batasannya: CSV harus punya header,
dan inferensi tipe bersifat heuristik.
