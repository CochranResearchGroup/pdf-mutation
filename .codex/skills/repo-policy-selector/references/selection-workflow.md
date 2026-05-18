# Selection Workflow

## Goal

Recommend the best starter policy profile and module composition for a target repo.

Selection is purpose-aware. Do not choose a profile until you have an explicit or inferred repo purpose.

Installation, policy enumeration, and downstream repo wiring should be deterministic.

## Installation first

Before selection in another repo:
- install the selector together with its policy library
- prefer a one-shot install path that places the pinned selector bundle under `.codex/skills/repo-policy-selector/` in the target repo and records the chosen git ref or local source
- prefer an installed selector bundle with a `release-manifest.json` so downstream repos can pin a reviewed bundle version
- confirm the installed bundle can enumerate:
  - profiles
  - modules
  - catalog metadata
  - by reading `catalog.yaml`, not by relying on hard-coded assumptions alone

## Inspect first

Read the target repo's:
- `AGENTS.md`
- `docs/dev/policies/`
- roadmap / runbook / progress files if present
- `docs/dev/plans/`, `docs/dev/notes/`, and `docs/dev/memories/` when present
- obvious repo-shape signals such as `package.json`, `pyproject.toml`, `tests/`, `docs/dev/`

Extract existing policy surfaces before recommending adoption changes.
That extraction should inventory current policy-bearing files and classify them against the installed templates as:
- `keep`
- `merge`
- `retire`

When `AGENTS.md` already contains substantive local guidance, infer repo-local policy sections and classify them as:
- `keep`
- `merge`
- `review-conflict`

Do not assume every section of an existing `AGENTS.md` should be replaced by the shared policy wire-in.
Treat `AGENTS.md` as a policy-loading contract, not just a static pointer:
- tell agents to re-read relevant policy files at the start of non-trivial turns
- tell agents to re-read relevant policy files when scope changes
- prefer explicit re-read triggers over assuming the initial file read remains sufficient for a long session

## Look for these signals

- roadmap/runbook discipline
- cluttered or legacy planning surfaces that need migration into canonical files
- cluttered or legacy notes/memories that need migration into canonical directories
- multiple active lanes
- parallel work or worktree usage
- multi-agent or delegated execution
- subagent runtime operation, including spawn depth, session ids, transcript paths, announce payloads, tool policy, and concurrency limits
- explicit closeout policy
- evidence of policy drift or anti-drift corrections
- whether the repo is a product repo, simple library, or skill/prompt/policy repo
- whether the repo is fundamentally a writing-project workspace with deliverable-driven organization
- whether the repo is fundamentally an operations-platform workspace with tenant-scoped runtime state, live operator workflows, and fieldwork that later becomes product
- whether the repo is fundamentally a course-workspace with LMS-backed live course operations, cloud-drive course materials, and student-data or assessment risk
- whether the repo is fundamentally a website-maintenance workspace with live-surface targeting, DB-backed state, drift reconciliation, or visual release QA
- whether the repo is fundamentally a formative seminal workspace whose operating model does not fit the existing families cleanly yet
- whether the repo uses an installed durable graph-memory system and needs explicit read/write/cleanup discipline in addition to notes and memories
- whether the repo produces local artifacts, reports, review packets, rendered documents, or local builds that should be surfaced through a preview or approval service for human review

For course workspaces, prioritize operational signals over generic document-folder shape:
- LMS config such as `canvas-cli.yml`
- live course ids or environment names
- assignment, submission, grading, quiz, module, roster, announcement, exam, seminar, or lecture folders
- student-data, FERPA, reflection, evaluation, response, grade, rubric, answer-key, or private-feedback language
- cloud-drive placeholders such as `.gsheet`, `.gform`, `.gdoc`, or `.gslides`
- Google Drive, OneDrive, or similar provider-native folder ids and connector workflows

For graph-backed memory usage, prioritize signals such as:
- installed graph-memory tools or MCP usage
- graph-backed durable memory language
- explicit memory-discovery skill, atlas, routing, or group-id guidance
- explicit read-before-re-ask memory guidance
- duplicate-write or memory-spam concerns
- destructive memory-maintenance tools that require explicit caution

For subagent runtime governance, prioritize signals such as:
- subagent run ids, session ids, session keys, transcript paths, logs, or announce payloads
- non-blocking spawn, timeout, cancellation, cascade-stop, archive, or cleanup behavior
- maximum spawn depth, nested subagents, child limits, or global concurrency caps
- tool allow/deny policy for spawned agents
- token, model, cost, or runtime stats on spawned work

For preview artifact review, prioritize signals such as:
- an available previews or browser-review skill/service
- generated local artifacts that are hard to inspect from terminal output alone
- review packets, approval packets, dry-run artifacts, reports, rendered docs, PDFs, Office documents, screenshots, galleries, or local HTML builds
- explicit approval workflow language that requires human feedback before a mutation, release, send, upload, or publish step

## Purpose classification

Pick the repo purpose first:

- `product-engineering`
- `operations-platform`
- `website-maintenance`
- `course-workspace`
- `library-cli`
- `seminal-workspace`
- `workspace-agent`
- `writing-project`

Then add a workflow subtype when it materially changes policy needs, for example:
- `grant-proposal-writing`
- `grant-proposal-review`
- `journal-article-writing`
- `patent-application-writing`

Then add execution bias when it materially changes coordination policy:
- `max-dev-speed`
- `balanced`
- `max-token-efficiency`

## Selection output

Return:
- inferred `repo_purpose`
- inferred `workflow_subtype` when applicable
- inferred `execution_bias` when applicable
- recommended profile
- recommended modules
- recommendation mode such as `full-profile` or `patch-missing`
- next modules to add when the repo already partially matches the selected profile
- deterministic install-plan entries with target local policy paths and rendered draft content
- an `AGENTS.md` wire-in patch for the planned policy set
- update-discovery reports that compare the installed pinned bundle against the latest published GitHub release without changing the installed policy source
- upgrade reports that compare an adopting repo's current policy coverage against a newer policy-library ref when a baseline tag or commit is available
- deterministic upgrade action plans that classify modules as install, upgrade-review, or retire-review
- installed bundle release metadata and, when available, baseline/current bundle release metadata resolved from upstream refs
- retirement cleanup patches that show which local policy files would be removed and how `AGENTS.md` would be rewired if retirement is accepted
- adoption mode such as `clean-adoption` or `migration-first`
- migration targets when cluttered planning or notes/memories are detected
- extracted existing policy surfaces
- inferred repo-local policy findings from existing `AGENTS.md` sections
- per-surface migration actions such as `keep`, `merge`, or `retire`
- extracted plan, note, and memory migration surfaces
- validation problems if recommended profiles/modules are missing from the installed library
- strong signals observed
- gaps between current local policy and selected shared policy
- whether to patch `docs/dev/policies/` and the `AGENTS.md` wire-in now or only produce a recommendation

Prefer the higher-level `scripts/manage_policy.py` entrypoint when the caller wants one command family for:
- adoption planning
- draft writing
- update checks against the latest published GitHub release
- upgrade checks
- upgrade action planning
- release-bundle preparation for the installed selector artifact
- deterministic release-note generation for tagged selector bundles
- GitHub release publication using checked-in release-note markdown
- end-to-end selector release cutting from clean repo state
- one-shot downstream installation with optional draft-writing
