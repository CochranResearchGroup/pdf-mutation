# Changelog

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
