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
python -m py_compile pdf_glyph_replace.py
python -m unittest discover -s tests -v
python -m build
pdf-glyph-replace --version
```

If your local Python installation blocks package installs, use a virtual
environment:

```bash
python -m venv work/dev-venv
work/dev-venv/bin/python -m pip install --upgrade pip build
work/dev-venv/bin/python -m build
work/dev-venv/bin/python -m pip install -e .
work/dev-venv/bin/pdf-glyph-replace --version
```

## Tests

Prefer synthetic QDF fixtures in unit tests. Tests should be small, deterministic,
and independent of private PDFs.

Add or update tests when a change affects:

- Content-stream parsing.
- Glyph replacement feasibility.
- Alignment behavior.
- Report JSON shape.
- CLI behavior.

## Release Changes

For versioned releases, keep these in sync:

- `pyproject.toml` version.
- `pdf_glyph_replace.__version__`.
- `CHANGELOG.md`.

Release tags use `vX.Y.Z`. Tag pushes build and upload release distributions
through GitHub Actions.
