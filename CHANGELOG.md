# Changelog

## v0.1.7 | Blocker Summary Reports

Maintenance release that makes unsupported split-object and mixed-font cases
easier to triage from non-sensitive plan and audit JSON.

### Added

- Plan and audit JSON now include a non-sensitive `blocker_summary` that
  aggregates unpatchable text-object reasons, split kinds, blocker reasons, and
  blocker fonts.

## v0.1.6 | Length Position Coverage

Maintenance release that broadens public length-changing alignment evidence
across match positions and makes bbox assertion diagnostics easier to inspect
without exposing decoded document text.

### Added

- Unit and public PDF smoke coverage for length-changing replacements when the
  match appears at the beginning, middle, or end of a one-glyph-per-line text
  object.
- Bbox alignment assertions now identify the checked coordinate and measured
  delta without embedding decoded document text.

## v0.1.5 | Public Length-Changing Fixture

Maintenance release that replaces private positive length-changing smoke
coverage with a public synthetic PDF fixture and tightens a start-of-text
alignment edge case.

### Added

- `pdf-fixture-qdf --pdf` for public, standalone synthetic PDF fixtures.
- Public length-changing smoke coverage for `--align left` and `--align right`
  using bbox edge assertions from a non-sensitive fixture.

### Fixed

- Length-changing replacements at the first glyph in a one-glyph-per-line text
  object no longer add an unintended leading `Td` before the first replacement
  glyph.

## v0.1.4 | Planner Apply Package Boundary

Product release that promotes the planner/apply workflow and importable Python
API boundary while preserving the existing `pdf-glyph-replace` CLI behavior.

### Added

- Importable `pdf_mutation` package boundary with public `engine`, `reports`,
  and `cli` modules.
- Internal `cmap`, `layout`, and `adapters` modules for CMap/object parsing,
  bbox layout evidence, and subprocess tool calls.
- Regression tests that verify public imports remain stable while
  implementation ownership moves out of the legacy script.

### Changed

- `pdf-glyph-replace` now resolves through `pdf_mutation.cli:main`.
- `pdf_mutation.engine` now focuses on planner, audit, apply, and report
  payload APIs rather than command-line orchestration.
- `pdf_glyph_replace.py` is now a compatibility wrapper for existing imports
  and direct script execution.

### Compatibility

- Existing CLI commands and direct `./pdf_glyph_replace.py` usage remain
  supported.
- Existing `pdf_glyph_replace` imports for planner/apply helpers and version
  metadata remain supported.
- New Python integrations should prefer `pdf_mutation.engine` for mutation APIs
  and `pdf_mutation.reports` for reporting/layout helpers.

### Known Limits

- Split cross-object or cross-font matches remain audit/plan-only unless a
  segmented replacement contract is implemented.
- Replacement glyphs must still exist in the active embedded font.
- Reports continue to omit decoded document text by default.

## v0.1.3 | Dogfood Summary Outputs

Maintenance release that improves the dogfood manifest summary surface for
release notes, runbooks, and operator evidence files.

### Added

- `pdf-dogfood-summary --markdown` for pasteable Markdown tables built from the
  same non-sensitive manifest summary rows as the TSV output.
- `pdf-dogfood-summary --output PATH` for writing TSV, JSON, Markdown, or
  health output directly to a file, creating parent directories when needed.

### Changed

- `pdf-dogfood-summary --json --markdown` now fails clearly instead of choosing
  one format implicitly.
- README and the dogfood runbook include direct Markdown file-output examples.

### Compatibility

- No glyph replacement behavior changed.
- Existing `pdf-dogfood-summary` stdout behavior is unchanged when `--output`
  is omitted.

## v0.1.2 | Dogfood Reporting

Maintenance release that adds the public dogfood inventory and manifest
reporting surface.

### Added

- `pdf-inventory` structural inventory command with JSON/TSV output, probe
  summaries, size guards, status summaries, and fail-on rules.
- `pdf-dogfood` wrapper for routine, complete, and readiness dogfood policies.
- Compact JSONL dogfood run manifests with non-literal probe metadata.
- `pdf-dogfood-summary` manifest table/JSON summaries, filters,
  latest-by-policy view, and manifest health gate.
- Manual GitHub Actions dogfood health workflow using a synthetic fixture and
  non-blocking workflow notices.

### Changed

- CI now compiles and smokes the inventory, dogfood, and manifest summary
  console entry points.
- Release source distributions include the synthetic dogfood manifest fixture
  used by tests.

## v0.1.1 | Release Automation Maintenance

Maintenance release that includes the public GitHub release automation added
after `v0.1.0`.

### Changed

- Build both wheel and source distribution in CI.
- Upload build distributions as workflow artifacts for every CI run.
- Upload release assets automatically for future `v*` tag pushes.
- Use current GitHub Actions runtimes for checkout, Python setup, and artifact
  upload actions.

## v0.1.0 | Initial Release

Initial release of `pdf-mutation`, a deterministic glyph-preserving PDF text
replacement CLI.

### Added

- `pdf-glyph-replace` console command and direct `pdf_glyph_replace.py` script.
- Exact replacement for same decoded glyph counts.
- Support for hexadecimal `<...> Tj` text and simple `[...] TJ` arrays.
- Support for multiple CIDs inside a single hexadecimal string operand.
- `--align right` for simple right-aligned, one-glyph-per-line amount edits.
- `--align left` for simple length-changing edits that preserve the original
  text matrix.
- `--dry-run` and `--dry-run --json` feasibility reports.
- `--report` non-sensitive JSON mutation reports.
- Synthetic QDF unit tests that do not depend on private PDF fixtures.
- Repo-local policy, roadmap, release metadata, and validation docs.

### Known Limits

- Replacement characters must already exist in the active PDF font CMap.
- Matches must fit inside one `BT ... ET` text object.
- Length-changing alignment modes require one-glyph-per-line hexadecimal `Tj`
  text with deterministic `Td` advances.
- The tool does not synthesize fonts, OCR text, redraw pages, edit encrypted
  PDFs, or reflow arbitrary paragraphs.
