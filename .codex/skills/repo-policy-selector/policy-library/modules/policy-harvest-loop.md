---
id: policy-harvest-loop
title: Policy Harvest Loop
summary: Capture reusable policy from successful sessions and normalize it back into reusable modules rather than leaving it trapped in one repo.
tags:
  - policy
  - harvesting
  - normalization
---

## Policy

- When a repo develops a strong local policy, decide whether it is:
  - repo-local only
  - reusable enough for the shared policy repo
- Prefer normalizing reusable rules into small modules rather than copying giant `AGENTS.md` sections wholesale.
- Preserve the original repo-specific wording only when the local context is essential.
- Harvest from:
  - repo `AGENTS.md`
  - repeated session behavior
  - runbook or antidrift patterns
  - branch and merge discipline that proved useful in practice
  - dated adoption feedback, notes, memories, and release notes
  - compact graph-memory facts when they are source-cited and verified against repo artifacts
- When a repo has an explicit graph-memory group, query it before starting substantial harvest work so prior policy decisions and repeated friction are not rediscovered from scratch.
- After a harvest changes shared modules, profiles, selector behavior, or schema, mirror a compact source-cited summary into the policy memory group when the repo's Graphiti write workflow is available and safe.
- Do not harvest directly from unsourced memory facts. Treat graph memory as discovery and routing evidence until verified against repo files, artifacts, commits, or cited episodes.

## Adoption Notes

Use this module in policy repos and skill repos that curate reusable agent behavior.
