# Changelog

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
