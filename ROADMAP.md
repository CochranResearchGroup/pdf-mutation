# Roadmap

## Purpose

`pdf-mutation` is a deterministic CLI for glyph-preserving PDF text replacement.
It should mutate encoded PDF text while preserving embedded fonts, glyph CIDs,
text drawing operators, and layout semantics wherever the PDF structure allows.

## Current State

- `pdf_glyph_replace.py` supports exact same-glyph-count replacements.
- `--align right` supports length-changing replacements for simple
  right-aligned, one-glyph-per-line amount text objects.
- `--dry-run` reports decoded matches, active font resources, and replacement
  feasibility without writing an output PDF.
- Exact mode supports `<...> Tj`, simple `[...] TJ` arrays, and multiple CIDs
  inside one hexadecimal string operand.
- Dry-run reports split matches across text objects or font changes as
  infeasible instead of patching across layout boundaries.
- Length-changing replacements support explicit `--align left` and
  `--align right` contracts for simple one-glyph-per-line text objects, with
  dry-run x-shift diagnostics.
- `tests/` contains synthetic QDF fixtures for parser and replacement coverage;
  the repeatable unit tests do not depend on private PDFs.
- The tool reads Type0 font `/ToUnicode` CMaps, replaces CID glyph operands,
  rebuilds via `fix-qdf`, and validates cleanly with `qpdf --check`.
- Known tested cases:
  - `3807 -> 8304`
  - `37.34 -> 138.46 --align right`

## Principles

- Prefer deterministic structural PDF edits over visual redrawing.
- Preserve original fonts and glyph encodings; fail clearly when a replacement
  character is not available in the active font.
- Keep unsupported text forms explicit instead of guessing.
- Validation must include extracted text and PDF structure checks; use bbox
  checks when layout preservation matters.
- Treat `work/` as scratch output unless an artifact is deliberately promoted.

## Milestones

### M1 | Harden The Existing CLI

Status: CLOSED

Goal: Make the current supported cases reliable enough for routine local use.

Scope:
- Add a small test suite around CMap parsing, exact replacement, and
  right-aligned amount replacement.
- Add fixture-generation or fixture-selection notes so tests do not depend on
  private PDFs.
- Improve error messages for missing tools, missing CMaps, unsupported glyphs,
  and unsupported text-object shapes.
- Add a `--dry-run` mode that reports decoded matches, active font resources,
  and replacement feasibility without writing an output PDF.

Acceptance Criteria:
- `python3 -m py_compile pdf_glyph_replace.py` passes.
- A repeatable test command exercises exact and right-aligned replacement.
- Dry-run output is deterministic and does not mutate files.
- README documents the tested command set.

Completion Notes:
- Added `python3 -m unittest discover -s tests -v` coverage for CMap parsing,
  exact CID replacement, right-aligned replacement, and dry-run feasibility.
- Added `--dry-run` and `--json` reporting.
- Added `.gitignore` entries for scratch PDFs, QDFs, and Python cache output.

### M2 | Broaden PDF Text Operator Support

Status: CLOSED

Goal: Support common encoded text structures beyond one `<...> Tj` sequence.

Scope:
- Support `TJ` arrays containing hex strings and spacing adjustments.
- Support multiple CIDs inside one hex operand while preserving grouping where
  possible.
- Detect and report matches split across multiple text objects or font changes.
- Preserve conservative failure behavior for structures that cannot be edited
  safely.

Acceptance Criteria:
- Exact replacement works for `<...> Tj` and simple `TJ` arrays.
- Unsupported split-match cases produce actionable diagnostics.
- Existing M1 smoke cases still pass unchanged.

Completion Notes:
- Added shared hex-string token handling for `<...> Tj`, simple `[...] TJ`
  arrays, and multi-CID hex operands.
- Added dry-run diagnostics for matches that appear only when text objects are
  concatenated.
- Added unit coverage for `TJ` arrays, multi-CID operands, and split-match
  infeasibility.

### M3 | Layout Policies Beyond Right Alignment

Status: CLOSED

Goal: Add explicit, opt-in layout policies for length-changing replacements.

Scope:
- Keep `--align right` as the default amount-column policy.
- Add `--align left` only when it can preserve the original text matrix and
  deterministic glyph advances.
- Add diagnostics that show old and new bbox estimates when possible.
- Refuse center or proportional adjustment until there is a reliable structural
  basis for it.

Acceptance Criteria:
- Each length-changing mode has a documented alignment contract.
- Right-aligned amount replacement still preserves the right edge in bbox
  extraction.
- Unsafe length-changing replacement attempts fail with clear guidance.

Completion Notes:
- Added `--align left`, which preserves the original text matrix and extends
  text using deterministic glyph advances.
- Kept `--align right` as the right-edge-preserving policy and added dry-run
  `estimated_x_shift` diagnostics.
- Added unit coverage for left alignment, right alignment diagnostics, and
  alignment contract reporting.

### M4 | Packaging And Release

Status: CLOSED

Goal: Make the tool easy to install and version without changing its core
behavior.

Scope:
- Add `pyproject.toml` with a console script entrypoint.
- Define a minimal semantic versioning policy for the CLI.
- Add dependency checks for `qpdf` and `fix-qdf` to install docs.
- Keep generated PDFs and QDFs out of source control unless they are explicit
  fixtures.

Acceptance Criteria:
- The CLI can run through an installed console command.
- README includes install, smoke, and release instructions.
- Release notes can describe supported PDF structures and known limits.

Completion Notes:
- Added `pyproject.toml` with package metadata and the
  `pdf-glyph-replace` console script.
- Added `pdf_glyph_replace.__version__` and `--version`; current version is
  `0.1.1`.
- Documented venv-based editable install, release gate, wheel build, external
  tool requirements, and semantic versioning.
- Added ignore rules for package metadata and build outputs.

### M5 | Safety And Review Workflow

Status: CLOSED

Goal: Make high-confidence PDF mutation review easier before replacing source
documents.

Scope:
- Add an optional report file with match count, font resource, object location,
  and validation hints.
- Add optional before/after text extraction snippets for each replacement.
- Consider an output naming convention that avoids overwriting inputs unless an
  explicit `--in-place` flag is added later.

Acceptance Criteria:
- Operators can inspect what changed without opening the PDF.
- Reports avoid dumping sensitive full-document text by default.
- In-place mutation remains unavailable or explicitly guarded.

Completion Notes:
- Added `--report` for dry-run and write modes.
- Reports include match counts, stream object ids, text object ids, font
  resources, alignment policy, short hashes of search/replacement strings, and
  validation hints.
- Reports intentionally omit full decoded text and literal search/replacement
  strings by default.
- The CLI still requires an explicit output path for mutation; no in-place mode
  was added.

## Deferred

- Visual redaction or raster editing.
- OCR-based replacement.
- Font synthesis or adding glyphs that are absent from the PDF.
- Reflowing paragraphs or replacing text across arbitrary layout boundaries.
- Editing encrypted PDFs.

## Validation Baseline

For code changes, run:

```bash
python3 -m py_compile pdf_glyph_replace.py
```

For PDF mutation smoke tests, run targeted commands such as:

```bash
./pdf_glyph_replace.py tmp.before-travel.pdf 3807 8304 -o work/smoke.8304.pdf
qpdf --check work/smoke.8304.pdf
pdftotext work/smoke.8304.pdf - | rg '8304|3807'

./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align right -o work/smoke.amount.pdf
qpdf --check work/smoke.amount.pdf
pdftotext work/smoke.amount.pdf - | rg '138\.46|37\.34'
pdftotext -bbox work/smoke.amount.pdf work/smoke.amount.bbox.html
rg '138\.46' work/smoke.amount.bbox.html
```
