# pdf-mutation

Deterministic glyph-preserving PDF text replacement experiments.

## Tool

`pdf_glyph_replace.py` rewrites encoded PDF text without changing fonts,
coordinates, drawing operators, or layout spacing. It works by:

1. converting the input PDF to QDF with `qpdf`;
2. reading Type0 font `/ToUnicode` CMaps;
3. decoding hexadecimal `Tj` glyph operands inside text objects;
4. replacing only the glyph CIDs for matching decoded text;
5. rebuilding a valid PDF with `fix-qdf` and `qpdf`.

## Usage

The script can be run directly:

```bash
./pdf_glyph_replace.py input.pdf 3807 8304 -o output.pdf
```

Or installed as a local console command:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
pdf-glyph-replace --version
pdf-fixture-qdf --version
pdf-inventory --version
pdf-dogfood --version
pdf-dogfood-summary --version
pdf-glyph-replace input.pdf 3807 8304 -o output.pdf
```

The CLI requires `qpdf` and `fix-qdf` on `PATH`. For validation workflows,
`pdftotext` and `pdftotext -bbox` from Poppler are also expected.

For length-changing replacements where the right edge should stay fixed, use
`--align right`:

```bash
./pdf_glyph_replace.py input.pdf 37.34 138.46 --align right -o output.pdf
```

For supported length-changing replacements where the left edge and original
text matrix should stay fixed, use `--align left`:

```bash
./pdf_glyph_replace.py input.pdf 37.34 138.46 --align left -o output.pdf
```

To inspect the edited QDF:

```bash
./pdf_glyph_replace.py input.pdf 3807 8304 -o output.pdf --keep-qdf work/output.qdf.pdf
```

To check decoded matches and feasibility without writing a PDF:

```bash
./pdf_glyph_replace.py input.pdf 3807 8304 --dry-run
./pdf_glyph_replace.py input.pdf 37.34 138.46 --align right --dry-run --json
./pdf_glyph_replace.py input.pdf 37.34 138.46 --align left --dry-run --json
```

To write a non-sensitive JSON report:

```bash
./pdf_glyph_replace.py input.pdf 3807 8304 -o output.pdf --report work/report.json
```

The report records match counts, font resources, stream object ids, text object
ids, alignment policy, and validation hints. It does not include full decoded
text or literal search/replacement strings by default.

## Synthetic Fixtures

Use `pdf-fixture-qdf` to create public, non-sensitive QDF fixtures for issues,
tests, and repros:

```bash
pdf-fixture-qdf 3807 -o work/fixture.qdf
pdf-fixture-qdf '$37.34' --one-glyph-per-line --x 653.375 --y 1370 -o work/amount.qdf
```

The fixture helper emits a minimal QDF-like byte stream with a synthetic Type0
font, `/ToUnicode` CMap, and hexadecimal text operands. It is designed for
testing `pdf_glyph_replace` parsing and replacement logic without sharing
private PDFs.

The same helper is available from Python:

```python
import pdf_fixture

qdf = pdf_fixture.synthetic_qdf("3807")
amount_qdf = pdf_fixture.synthetic_qdf(
    "$37.34",
    one_glyph_per_line=True,
    x="653.375",
    y="1370",
)
```

The synthetic font intentionally contains only a small glyph set used by the
tests and examples. If a repro needs more characters, extend the synthetic map
in code rather than attaching a real private document.

## PDF Inventory

Use `pdf-inventory` to classify PDFs without mutating files or extracting
document text:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --json work/dogfood-pdfs/inventory/inventory.json \
  --tsv work/dogfood-pdfs/inventory/inventory.tsv
```

The command reports structural support signals: `qpdf` validity, QDF conversion,
object and stream counts, Type0 font count, `/ToUnicode` references, decoded
font resource count, and text-object count. Unsupported-but-valid PDFs are
reported with `status: "unsupported"` and exit code 0; only hard errors such as
missing files or failed `qpdf --check` make the command fail.

Add `--probe SEARCH REPLACEMENT` to include non-mutating match feasibility
signals in the inventory:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --probe 3807 8304 \
  --summary \
  --json work/dogfood-pdfs/inventory/probed.json
```

Probe output includes search/replacement lengths, short hashes, match counts,
feasibility status, and infeasible reasons. It does not include literal probe
strings or decoded document text.

Use `--summary` to include aggregate counts by inventory status and probe
status. The JSON output becomes an object with `rows` and `summary`; TSV remains
row-oriented.

Use `--max-input-bytes` to skip QDF conversion for very large PDFs during broad
corpus scans:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --max-input-bytes 50000000 \
  --summary
```

Skipped PDFs are reported with `status: "skipped"` and still contribute to the
summary counts. This avoids expanding large inputs into much larger QDF files
unless explicitly needed.

Use `--fail-on` to turn inventory reports into deterministic corpus gates:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --probe 3807 8304 \
  --max-input-bytes 50000000 \
  --fail-on error qdf-conversion-failed probe-feasible
```

The command exits 2 when any selected rule matches and prints the matching rows
to stderr. Available rules are `error`, `unsupported`, `skipped`,
`qpdf-check-failed`, `qdf-conversion-failed`, `probe-unsupported`,
`probe-no-match`, `probe-infeasible`, `probe-feasible`, and `probe-match`.

For repeatable local corpus checks, see
`docs/dev/dogfood-runbook.md`.

The same routine dogfood gate is available as a wrapper command:

```bash
pdf-dogfood --probe 3807 8304
```

By default, `pdf-dogfood` scans `work/dogfood-pdfs/sample-*.pdf`, writes
`work/dogfood-pdfs/inventory/dogfood.json` and `.tsv`, applies
`--max-input-bytes 50000000`, and fails on `error`, `qpdf-check-failed`,
`qdf-conversion-failed`, or `probe-feasible`.
Use `--policy complete` to fail on skipped files as well, or
`--policy readiness --probe SEARCH REPLACEMENT` to require a clean supported
probe match.
Dogfood JSON reports include a `policy` block with the wrapper version,
selected policy, effective fail-on rules, size guard, input glob, report paths,
and hashed probe metadata.
Use `--manifest` to append a compact JSONL run history record; with no path
argument it writes to `work/dogfood-pdfs/inventory/dogfood-manifest.jsonl`.
Use `pdf-dogfood-summary` to print recent manifest records as a TSV table:

```bash
pdf-dogfood-summary --limit 10
pdf-dogfood-summary --latest-by-policy
pdf-dogfood-summary --latest-by-policy --markdown
pdf-dogfood-summary --latest-by-policy --markdown --output work/dogfood-pdfs/inventory/latest.md
pdf-dogfood-summary --health
pdf-dogfood-summary --fail-only --policy readiness
pdf-dogfood-summary --exit-code 2 --json
```

For an Actions-side check, run the `CI` workflow manually from GitHub Actions
and use its `dogfood_manifest` input. The manual `Dogfood manifest health` job
defaults to `tests/fixtures/dogfood-manifest.jsonl`, reports the `--health`
exit status as a notice, and does not require private PDFs in the repository.

## Validation

Run the source-level tests:

```bash
python3 -m py_compile pdf_glyph_replace.py pdf_fixture.py pdf_inventory.py
python3 -m unittest discover -s tests -v
pdf-glyph-replace --version
pdf-fixture-qdf --version
pdf-inventory --version
pdf-dogfood --version
pdf-dogfood-summary --version
```

Run local PDF smoke tests when fixture PDFs are available:

```bash
./pdf_glyph_replace.py tmp.before-travel.pdf 3807 8304 --dry-run
./pdf_glyph_replace.py tmp.before-travel.pdf 3807 8304 -o work/smoke.8304.pdf --report work/smoke.8304.report.json
qpdf --check work/smoke.8304.pdf
pdftotext work/smoke.8304.pdf - | rg '8304|3807'

./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align right --dry-run
./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align right -o work/smoke.amount.pdf
qpdf --check work/smoke.amount.pdf
pdftotext work/smoke.amount.pdf - | rg '138\.46|37\.34'
pdftotext -bbox work/smoke.amount.pdf work/smoke.amount.bbox.html
rg '138\.46' work/smoke.amount.bbox.html

./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align left --dry-run
./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align left -o work/smoke.amount-left.pdf
qpdf --check work/smoke.amount-left.pdf
pdftotext work/smoke.amount-left.pdf - | rg '138\.46|37\.34'
```

## Versioning And Release

The CLI uses semantic versioning. The package version in `pyproject.toml` and
`pdf_glyph_replace.__version__` must stay in sync.
See `CHANGELOG.md` for release notes and `docs/dev/RELEASE_CHECKLIST.md` for
the full release checklist.

Release gate:

```bash
python3 -m py_compile pdf_glyph_replace.py pdf_fixture.py pdf_inventory.py pdf_dogfood.py pdf_dogfood_summary.py
python3 -m unittest discover -s tests -v
python3 -m venv work/release-venv
work/release-venv/bin/python -m pip install -e .
work/release-venv/bin/pdf-glyph-replace --version
work/release-venv/bin/pdf-fixture-qdf --version
work/release-venv/bin/pdf-inventory --version
work/release-venv/bin/pdf-dogfood --version
work/release-venv/bin/pdf-dogfood-summary --version
work/release-venv/bin/python -m pip wheel . -w work/dist
```

For behavior-changing releases, also run the local PDF smoke tests above when
fixture PDFs are available. Release notes should describe newly supported PDF
text structures and known limits.

## Current Scope

This first version is intentionally strict by default:

- default `--align exact` requires search and replacement to have the same
  decoded glyph count;
- `--align right` supports length-changing replacements only for simple
  one-glyph-per-line text objects and shifts the text matrix to preserve the
  right edge;
- `--align left` supports the same simple one-glyph-per-line text objects and
  preserves the original text matrix;
- dry-run reports the active alignment contract and estimated text-matrix
  x-shift for length-changing modes;
- `--report` writes a non-sensitive JSON report with match locations, font
  resources, and validation hints;
- replacement characters must already exist in the active PDF font CMap;
- matches must fit inside one `BT ... ET` text object;
- supported exact-mode text drawing forms are hexadecimal `<...> Tj` and simple
  `[...] TJ` arrays with hexadecimal string entries;
- exact mode supports multiple CIDs inside one hexadecimal string operand;
- matches split across text objects or font changes are reported as infeasible
  by dry-run instead of being patched.

That covers deterministic token changes such as account suffixes and IDs, plus
simple right-aligned amount edits in PDFs that emit each glyph as a separate
`Tj` line with `Td` advances.
