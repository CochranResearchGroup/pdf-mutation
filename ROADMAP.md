# Roadmap

## Product Goal

`pdf-mutation` is a deterministic PDF mutation CLI and library for replacing
encoded PDF text while preserving embedded fonts, glyph CIDs, text drawing
operators, and layout semantics wherever the PDF structure allows.

The product must answer four questions before it edits a file:

1. Can the target text be found structurally?
2. Can the replacement be expressed with glyphs already embedded in the PDF?
3. Can layout semantics be preserved under an explicit alignment contract?
4. If not, what exact PDF structure blocks the mutation?

The core product is mutation planning and application. Corpus dogfood,
inventory, and release evidence exist only to validate and explain that product.

## Current Product Surface

- `pdf-glyph-replace` mutates Type0 `/ToUnicode` text that is encoded as
  hexadecimal `<...> Tj` operands or simple `[...] TJ` arrays.
- Default `--align exact` replaces same decoded glyph counts while preserving
  existing drawing operators and layout.
- `--align left` and `--align right` support length-changing replacements only
  for simple one-glyph-per-line text objects with deterministic `Td` advances.
- `--dry-run` reports matching text objects, feasibility, active font
  resources, and alignment diagnostics.
- `--audit` inventories every decoded text object, reports mixed-font or
  cross-object split matches, and omits full decoded document text.
- `--plan` writes a reviewable JSON mutation plan for same-glyph-count
  patchable matches and unpatchable candidates without applying it.
- `--report` writes non-sensitive mutation reports with match locations, font
  resources, short search/replacement hashes, and validation hints.
- `pdf-fixture-qdf` provides synthetic QDF fixtures for public tests and repros.
- `pdf-inventory`, `pdf-dogfood`, and `pdf-dogfood-summary` support corpus
  validation and release evidence. They are not the main product lane.

## Product Principles

- Prefer deterministic structural PDF edits over overlays, raster edits, OCR, or
  redrawing.
- Preserve original fonts and glyph encodings; fail when replacement characters
  are absent from the active font.
- Treat mixed-font, split-object, and layout-changing cases as planning facts
  first. Add mutation support only after the structural contract is explicit.
- Keep reports non-sensitive by default: object IDs, counts, hashes, and
  feasibility reasons are acceptable; full decoded document text is not.
- Require validation that the output is a valid PDF and that extracted text
  reflects the intended mutation.

## Forward Milestones

### M7 | Mutation Planner

Status: DONE

Goal: Make planning a first-class product surface that can be reviewed,
stored, and applied later.

Scope:
- Add a stable plan JSON schema for patchable matches.
- Include input fingerprint, search/replacement hashes, alignment policy,
  stream object, text object index, font resource, glyph span, and feasibility.
- Add `--plan PATH` to write the plan without mutating the PDF.
- Add expected-count fields and reasons for every unpatchable candidate.
- Keep decoded document text and literal search/replacement strings out of the
  plan by default.

Acceptance Criteria:
- A plan generated from a supported exact replacement can be applied in a later
  process without re-deciding match boundaries.
- The plan clearly distinguishes patchable matches, unpatchable same-object
  matches, and split cross-object or cross-font matches.
- Unit tests cover exact `Tj`, `TJ`, multi-CID operands, missing glyphs, and
  mixed-font split candidates.

Progress:
- Added the first `--plan PATH` surface for same-glyph-count patchable matches,
  missing replacement glyphs, and split candidates.
- Completed the initial plan/apply loop through M8's exact-plan application
  surface.

### M8 | Plan Apply And Match Guards

Status: DONE

Goal: Apply only the reviewed plan and fail closed when the source PDF shape
changes.

Scope:
- Add `--apply-plan PATH`.
- Add `--expect-count N` for direct CLI use and plan application.
- Recompute structural fingerprints before writing.
- Emit a post-apply report linking each changed glyph span to the plan entry.
- Preserve the current refusal behavior for split cross-object and cross-font
  matches.

Acceptance Criteria:
- Applying a stale plan fails before writing an output PDF.
- Applying a valid plan mutates all and only the planned patchable matches.
- Post-apply reports include plan ID, changed match count, skipped/unapplied
  count, and validation hints.

Progress:
- Added initial `--apply-plan PATH` support for same-glyph-count patchable
  plans, with input fingerprint checks, QDF span verification, and
  non-sensitive post-apply reports.
- Added `--expect-count N` guards for direct writes, dry-runs, audits, plan
  generation, and plan application.

### M9 | Mixed-Font Strategy

Status: DONE

Goal: Turn mixed-font documents from vague unsupported cases into explicit,
deterministic behavior.

Scope:
- Keep same-object, same-font matches patchable when replacement glyphs exist.
- Keep cross-font and cross-object matches audit-only unless a segmented
  replacement contract is designed.
- Design segmented replacement as a separate plan type before implementation.
- Add tests for adjacent objects, font switches inside apparent words, and
  replacement glyphs missing in only one segment.

Acceptance Criteria:
- The planner explains exactly which font resource blocks each candidate.
- No cross-font mutation is attempted without an explicit segmented plan.
- Mixed-font documents remain useful audit inputs even when no mutation is
  possible.

Progress:
- Added explicit split candidate segment metadata and font-specific blockers.
- Documented the future segmented-plan contract in
  `docs/dev/segmented-plan-contract.md`; split candidates remain unpatchable
  under the current plan schema.
- Added tests for adjacent same-font objects, cross-font apparent words, and a
  replacement glyph missing in only one segment.

### M10 | Layout Evidence

Status: DONE

Goal: Make layout preservation observable, not assumed.

Scope:
- Add optional bbox extraction helpers around Poppler `pdftotext -bbox`.
- Record before/after bbox evidence for changed text where available.
- Add right-edge and left-edge assertions for supported alignment contracts.
- Produce optional HTML or JSON inspection artifacts under `work/`.

Acceptance Criteria:
- Length-changing replacements can prove their claimed alignment contract.
- Exact replacements record that text extraction changed while glyph layout
  operators stayed structurally stable.
- Missing external layout tools produce clear validation warnings instead of
  mutation failures.

Progress:
- Added optional `--bbox-dir PATH` evidence generation for write/apply modes
  with `--report`.
- Reports now record before/after bbox artifact paths, sizes, short hashes, and
  warnings without embedding extracted bbox text.
- Direct-write reports now summarize exact-mode before/after extraction counts
  and numeric left/right bbox edge assertions for alignment modes.

### M11 | Engine And CLI Boundary

Status: IN PROGRESS

Goal: Split reusable mutation logic from command-line orchestration.

Scope:
- Move parsing, planning, applying, and reporting into importable modules.
- Keep `pdf_glyph_replace.py` as a thin CLI wrapper or compatibility shim.
- Define a stable Python API for plan generation and application.
- Keep subprocess calls to `qpdf`, `fix-qdf`, and optional Poppler tools behind
  a narrow adapter.

Acceptance Criteria:
- Unit tests can exercise planner/apply behavior without invoking the CLI.
- CLI behavior remains backward compatible for current commands.
- External callers can build a plan and apply it through Python without parsing
  CLI output.

Progress:
- Added the `pdf_mutation` package namespace with `engine`, `reports`,
  `adapters`, and `cli` modules.
- Moved the console script entrypoint to `pdf_mutation.cli:main` while keeping
  `pdf_glyph_replace.py` as the compatibility implementation.
- Moved the current implementation body into `pdf_mutation.engine` and reduced
  `pdf_glyph_replace.py` to a compatibility wrapper.
- Split CMap/object parsing and subprocess helpers into internal package
  modules while preserving the `pdf_mutation.engine` public exports.
- Split bbox layout evidence into an internal `pdf_mutation.layout` module
  while preserving public reporting imports through `pdf_mutation.reports`.
- Added import-level API tests for engine and reporting helpers.

### M12 | Product Release Candidate

Status: PLANNED

Goal: Cut the next release only after the planner/apply product loop is
coherent.

Scope:
- Release after M7 and M8 are complete; include M9-M11 only if they are ready.
- Release notes describe actual mutation capability, not dogfood refinements.
- Run source tests, package build, installed CLI smoke, local fixture smoke, and
  published wheel smoke.

Acceptance Criteria:
- The release has a documented planner/apply workflow.
- The release has a clear compatibility statement for existing CLI users.
- Dogfood evidence supports the release but does not define its direction.

## Supporting Infrastructure Lane

The following work is useful, but should not displace mutation-engine progress:

- Improve `pdf-inventory` corpus classification when it directly informs M7-M10.
- Keep `pdf-dogfood` policies current enough to validate supported structures.
- Keep release evidence concise and tied to actual mutation capabilities.
- Avoid release cuts for dogfood-only polish unless a real consumer workflow
  depends on it.

## Deferred

- Visual redaction or raster editing.
- OCR-based replacement.
- Font synthesis or adding glyphs that are absent from the PDF.
- Reflowing paragraphs or replacing text across arbitrary layout boundaries.
- Editing encrypted PDFs.
- In-place mutation without an explicit reviewed plan and backup policy.

## Validation Baseline

For code changes:

```bash
python3 -m py_compile pdf_glyph_replace.py pdf_fixture.py pdf_inventory.py pdf_dogfood.py pdf_dogfood_summary.py
python3 -m unittest discover -s tests -v
```

For PDF mutation smoke tests when local fixture PDFs are available:

```bash
./pdf_glyph_replace.py tmp.before-travel.pdf 3807 8304 --audit --json --report work/audit.json
./pdf_glyph_replace.py tmp.before-travel.pdf 3807 8304 --dry-run
./pdf_glyph_replace.py tmp.before-travel.pdf 3807 8304 -o work/smoke.8304.pdf --report work/smoke.8304.report.json
qpdf --check work/smoke.8304.pdf
pdftotext work/smoke.8304.pdf - | rg '8304|3807'

./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align right --dry-run
./pdf_glyph_replace.py tmp.before-travel.pdf 37.34 138.46 --align right -o work/smoke.amount.pdf --report work/smoke.amount.report.json
qpdf --check work/smoke.amount.pdf
pdftotext work/smoke.amount.pdf - | rg '138\.46|37\.34'
pdftotext -bbox work/smoke.amount.pdf work/smoke.amount.bbox.html
rg '138\.46' work/smoke.amount.bbox.html
```

## Completed History

### M1 | Harden The Existing CLI

Status: CLOSED

Completed:
- Added unit coverage for CMap parsing, exact CID replacement, right-aligned
  replacement, and dry-run feasibility.
- Added `--dry-run` and JSON reporting.
- Added scratch-file ignore rules.

### M2 | Broaden PDF Text Operator Support

Status: CLOSED

Completed:
- Added support for `<...> Tj`, simple `[...] TJ` arrays, and multi-CID hex
  operands.
- Added diagnostics for matches split across text objects or font changes.
- Added tests for `TJ` arrays, multi-CID operands, and split-match refusal.

### M3 | Layout Policies Beyond Right Alignment

Status: CLOSED

Completed:
- Added `--align left` for simple one-glyph-per-line text objects.
- Kept `--align right` as the right-edge-preserving policy.
- Added alignment contract and x-shift diagnostics.

### M4 | Packaging And Release

Status: CLOSED

Completed:
- Added `pyproject.toml`, package metadata, and console entry points.
- Added `--version` surfaces and release docs.
- Added build, install, and release validation guidance.

### M5 | Safety And Review Workflow

Status: CLOSED

Completed:
- Added `--report` for dry-run and write modes.
- Reports include match counts, stream object IDs, text object IDs, font
  resources, alignment policy, short hashes, and validation hints.
- Full decoded text and literal search/replacement strings are omitted by
  default.

### M6 | Dogfood Reporting And Release Evidence

Status: CLOSED

Completed:
- Added `pdf-inventory`, `pdf-dogfood`, and `pdf-dogfood-summary`.
- Added compact non-sensitive dogfood manifest records and a synthetic fixture.
- Added Markdown and file-output modes for dogfood summaries.
- CI builds distributions and smokes installed console entry points.
