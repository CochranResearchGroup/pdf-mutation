# Dogfood Runbook

Use this runbook to inventory local PDF samples without committing private
documents or generated reports.

The routine gate can be run with the wrapper command:

```bash
pdf-dogfood --probe 3807 8304
```

By default, this expands `work/dogfood-pdfs/sample-*.pdf`, writes JSON and TSV
reports under `work/dogfood-pdfs/inventory/`, applies `--max-input-bytes
50000000`, and uses the routine fail-on policy from this runbook.
Use `--policy complete` or `--policy readiness` to select the other runbook
gate profiles.

## Corpus Location

Keep dogfood PDFs under the ignored scratch tree:

```bash
work/dogfood-pdfs/
```

Do not commit PDFs copied from local downloads, private exemplars, generated
QDF files, or inventory reports. If a public repro is needed, create a synthetic
fixture with `pdf-fixture-qdf` and commit the source code that generates it
instead of the private PDF.

## Baseline Inventory

Run a broad structural inventory with summary output:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --summary \
  --json work/dogfood-pdfs/inventory/baseline.json \
  --tsv work/dogfood-pdfs/inventory/baseline.tsv
```

Use this when the question is corpus shape: valid PDFs, supported Type0
resources, text-object counts, and common unsupported reasons.

## Probe Inventory

Run a non-mutating probe when evaluating a specific search/replacement pair:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --probe 3807 8304 \
  --summary \
  --json work/dogfood-pdfs/inventory/probe-3807-8304.json \
  --tsv work/dogfood-pdfs/inventory/probe-3807-8304.tsv
```

Probe output records lengths, short hashes, match counts, feasibility, and font
resource counts. It does not include literal probe strings or decoded document
text.

## Large-File Guard

Use `--max-input-bytes` during broad scans so large PDFs are counted without QDF
expansion:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --probe 3807 8304 \
  --summary \
  --max-input-bytes 50000000 \
  --json work/dogfood-pdfs/inventory/probe-3807-8304-guarded.json \
  --tsv work/dogfood-pdfs/inventory/probe-3807-8304-guarded.tsv
```

Rows skipped by this guard report `status: "skipped"` and remain part of the
summary. Treat skipped rows as intentional coverage gaps until a narrower run
inspects them directly.

## Recommended Gates

For routine dogfood, fail only on hard processing errors or a probe that finds a
feasible mutation target:

```bash
pdf-dogfood --probe 3807 8304
```

Equivalent explicit `pdf-inventory` command:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --probe 3807 8304 \
  --summary \
  --max-input-bytes 50000000 \
  --fail-on error qpdf-check-failed qdf-conversion-failed probe-feasible \
  --json work/dogfood-pdfs/inventory/gate-routine.json \
  --tsv work/dogfood-pdfs/inventory/gate-routine.tsv
```

For corpus completeness checks, also fail on skipped rows:

```bash
pdf-dogfood --policy complete
```

Equivalent explicit `pdf-inventory` command:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --summary \
  --max-input-bytes 50000000 \
  --fail-on error qpdf-check-failed qdf-conversion-failed skipped \
  --json work/dogfood-pdfs/inventory/gate-complete.json
```

For targeted mutation readiness, fail when the probe does not find a clean
supported match:

```bash
pdf-dogfood --policy readiness --probe SEARCH REPLACEMENT
```

Equivalent explicit `pdf-inventory` command:

```bash
pdf-inventory work/dogfood-pdfs/sample-*.pdf \
  --probe SEARCH REPLACEMENT \
  --fail-on error unsupported skipped probe-unsupported probe-no-match probe-infeasible
```

`--fail-on` returns exit code 2 when a selected rule matches and writes a compact
row/rule table to stderr. Default inventory remains report-only except for hard
`status: "error"` rows.

## Review Checklist

- Confirm generated JSON and TSV reports are under `work/dogfood-pdfs/`.
- Confirm reports do not contain literal private search/replacement strings when
  using `--probe`.
- Confirm large skipped files are either acceptable for the current run or
  handled by a narrower command without `--max-input-bytes`.
- Confirm no PDFs are tracked:

```bash
git ls-files | rg '\.pdf$' || true
```
