# Pdf Mutation

## Repo Context

- This repo is a lightweight Python CLI workspace for deterministic, glyph-preserving PDF text replacement.
- The durable tool entrypoint is `pdf_glyph_replace.py`; `README.md` documents supported usage and current limits.
- `ROADMAP.md` is the canonical priority surface for planned tool hardening and feature work.
- `work/` is a scratch area for generated QDFs, smoke PDFs, bbox HTML, and rendered inspection artifacts. Do not treat files under `work/` as source unless a task explicitly says to preserve or promote one.
- The repo-local policy set is intentionally the `standalone-library` profile: keep coordination lightweight and validation concrete.

## Repo-Specific Guidance

- Prefer deterministic PDF mutation through `qpdf --qdf`, `/ToUnicode` CMap decoding, glyph CID replacement, `fix-qdf`, and final `qpdf` rebuild.
- Preserve embedded fonts, glyph encodings, text drawing operators, and layout semantics unless the task explicitly asks for a visual rewrite.
- For equal-length replacements, use default exact mode:
  - `./pdf_glyph_replace.py input.pdf 3807 8304 -o output.pdf`
- Installed CLI entrypoint:
  - `pdf-glyph-replace input.pdf 3807 8304 -o output.pdf`
- For simple right-aligned amount replacements, use:
  - `./pdf_glyph_replace.py input.pdf 37.34 138.46 --align right -o output.pdf`
- For supported length-changing replacements that should preserve the original text matrix, use:
  - `./pdf_glyph_replace.py input.pdf old new --align left -o output.pdf`
- For reviewable mutation summaries without full decoded text, use:
  - `./pdf_glyph_replace.py input.pdf old new -o output.pdf --report work/report.json`
- Validate PDF mutations with at least:
  - `python3 -m py_compile pdf_glyph_replace.py` when code changed
  - `python3 -m unittest discover -s tests -v` when behavior changed
  - `qpdf --check <output.pdf>`
  - `pdftotext <output.pdf> - | rg '<expected-or-old-text>'`
- Keep `pyproject.toml` and `pdf_glyph_replace.__version__` in sync for releases.
- Use `CHANGELOG.md` for release notes and `docs/dev/RELEASE_CHECKLIST.md` for release validation.
- When right-edge preservation matters, verify with bbox extraction:
  - `pdftotext -bbox <output.pdf> work/<name>.bbox.html`
- Reports must stay non-sensitive by default: include counts, object ids, font resources, hashes, and validation hints rather than full decoded document text.
- Keep replacement support honest: document unsupported PDF text forms instead of silently guessing across split text objects, missing CMaps, complex text arrays, or replacement characters absent from the active font.
- At closeout, always propose the best next turn unless the user explicitly asks to pause, stop, or only report status.

## Policy Loading Contract

- `AGENTS.md` is a routing surface, not a one-time pointer.
- Re-read the relevant policy files under `docs/dev/policies/` at the start of any non-trivial turn.
- Re-read the relevant policy files when task scope changes mid-session.
- When behavior is ambiguous, prefer re-reading policy over improvising from stale assumptions.

## Policy Re-read Triggers

- re-read planning-related policy before opening, revising, or closing a substantive plan
- re-read documentation-related policy before changing docs, contracts, or canonical authorities
- re-read validation and closeout policy before claiming work complete

## Policy Entry

This repo keeps its durable repo-local policy under `docs/dev/policies/`.

Read and follow:
- `docs/dev/policies/0001-policy-management.md`
- `docs/dev/policies/0002-policy-upgrade-management.md`
- `docs/dev/policies/0003-policy-adoption-feedback-loop.md`
- `docs/dev/policies/0004-git-worktree-hygiene.md`
- `docs/dev/policies/0005-commit-history-discipline.md`
- `docs/dev/policies/0006-branch-and-integration-strategy.md`
- `docs/dev/policies/0007-commit-and-push-cadence.md`
- `docs/dev/policies/0008-versioning-and-release.md`
- `docs/dev/policies/0009-turn-closeout.md`

## Scope

- `AGENTS.md` includes repo-local guidance plus the policy entry section.
- The durable policy body lives under `docs/dev/policies/`.
- Keep repo-specific commands, environment details, and operational caveats in this file or adjacent local docs.
