---
id: subagent-workflow-optimization
title: Subagent Workflow Optimization
summary: Delegate only well-bounded work, keep the primary agent on the critical path, and tune delegation behavior to the repo's execution bias.
tags:
  - agents
  - delegation
  - subagents
  - optimization
---

## Policy

- Delegate only concrete, bounded subtasks that materially advance the active slice.
- Keep urgent blocking work local when the next action depends directly on the answer.
- Give delegated work explicit ownership, expected output, and write scope.
- Prefer subagents for independent sidecar work, verification, or implementation slices with disjoint write sets.
- Do not spawn parallel work that duplicates context loading or repeats the same exploration without a clear benefit.
- Reuse prior agent context when the task is a continuation of the same bounded thread.
- Keep final integration responsibility with the primary agent even when subagents perform part of the work.
- Be explicit about whether the repo optimizes for wall-clock speed, token efficiency, or a balance of the two.
- Treat spawned subagents as asynchronous runtime artifacts, not just informal delegation.
- Record the subagent run id, session id, transcript path, or equivalent handle when the runtime provides one.
- Do not assume delegated work completed until an announce payload, status check, log read, or transcript inspection confirms completion.
- For critical or high-risk delegated work, inspect the transcript or logs instead of relying only on a summarized announce.
- Prefer subagent closeout that includes status, result, notes, and available runtime, token, or cost metadata.
- Set explicit timeout expectations for long-running, slow-tool, or uncertain delegated work.
- Use lower-cost or lower-reasoning models for bounded sidecar work only when the quality risk is low; keep synthesis, architecture, and final integration on an appropriately capable model.
- Treat subagent cleanup and transcript retention as deliberate choices when later evidence or reconciliation may matter.

## Adoption Notes

Use this module when repos actively rely on delegation or subagent orchestration rather than single-agent execution.

Execution-bias guidance:
- `max-dev-speed`: delegate earlier, parallelize more independent work, and accept some coordination overhead to reduce wall-clock time
- `balanced`: delegate bounded sidecar work and verification, but keep tightly coupled or critical-path work local
- `max-token-efficiency`: delegate only when the subtask is clearly independent and the expected gain exceeds the added context and reconciliation cost

Use `subagent-runtime-governance` as a companion module when the repo builds, configures, or operates the subagent runtime itself.
