# Contributing

Thanks for improving `pdf-mutation`. This project handles workflows that often
start from private PDFs, so contribution hygiene matters as much as code
correctness.

## Privacy Rules

Do not commit, attach, paste, or upload private PDFs, statements, receipts,
invoices, or sensitive document content.

Use one of these instead:

- A synthetic PDF generated only for the issue or test.
- A reduced QDF snippet that preserves the parser shape without real content.
- A tiny fixture built from made-up text, coordinates, and glyph mappings.
- Non-sensitive JSON from `--dry-run --json` or `--report`.

The `pdf-fixture-qdf` command can generate minimal public fixtures:

```bash
pdf-fixture-qdf 3807 -o work/fixture.qdf
pdf-fixture-qdf '$37.34' --one-glyph-per-line --x 653.375 --y 1370 -o work/amount.qdf
```

Keep scratch artifacts under ignored paths such as `work/` or local `tmp*.pdf`
files.

## Reporting Bugs

Use the bug report issue form. Include:

- The exact `pdf-glyph-replace` command.
- `pdf-glyph-replace --version`.
- Python, OS, `qpdf`, and related tool versions when relevant.
- A synthetic fixture or reduced QDF snippet.
- Expected behavior and actual behavior.

Do not use public issues for suspected vulnerabilities. Use GitHub private
vulnerability reporting instead.

## Requesting Features

Use the feature request issue form. Keep requests bounded and describe the PDF
structure with synthetic examples.

The current tool is intentionally strict. It preserves glyph use in existing
PDF content streams; it does not synthesize fonts, OCR text, redraw pages, edit
encrypted PDFs, or reflow arbitrary paragraphs.

## Pull Requests

Open pull requests against `main`. The branch is protected, so changes merge
through PR checks.

Before opening a PR, run:

```bash
python -m py_compile pdf_glyph_replace.py pdf_fixture.py pdf_inventory.py pdf_mutation/*.py
python -m unittest discover -s tests -v
python -m build
python -c "from pdf_mutation.engine import plan_qdf; print(plan_qdf.__name__)"
pdf-glyph-replace --version
pdf-fixture-qdf --version
pdf-inventory --version
```

If your local Python installation blocks package installs, use a virtual
environment:

```bash
python -m venv work/dev-venv
work/dev-venv/bin/python -m pip install --upgrade pip build
work/dev-venv/bin/python -m build
work/dev-venv/bin/python -m pip install -e .
work/dev-venv/bin/python -c "from pdf_mutation.engine import plan_qdf; print(plan_qdf.__name__)"
work/dev-venv/bin/pdf-glyph-replace --version
work/dev-venv/bin/pdf-fixture-qdf --version
work/dev-venv/bin/pdf-inventory --version
```

## Tests

Prefer synthetic QDF fixtures in unit tests. Tests should be small, deterministic,
and independent of private PDFs.

Use `pdf_fixture.synthetic_qdf`, `pdf_fixture.text_object`, and
`pdf_fixture.qdf_document` when adding parser or replacement tests. Extend the
synthetic glyph map when a test needs new public characters.

Add or update tests when a change affects:

- Content-stream parsing.
- Glyph replacement feasibility.
- Alignment behavior.
- Report JSON shape.
- CLI behavior.
- PDF inventory classification.
- PDF inventory probe summaries.

## Release Changes

For versioned releases, keep these in sync:

- `pyproject.toml` version.
- `pdf_glyph_replace.__version__`.
- `CHANGELOG.md`.

Release tags use `vX.Y.Z`. Tag pushes build and upload release distributions
through GitHub Actions.
