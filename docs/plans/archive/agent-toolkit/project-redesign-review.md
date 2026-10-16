# Agent Toolkit — consolidated redesign proposal

> tags: [planning, redesign, handoff]

Updated: 2026-10-12. Requirements interview complete through Q18.
Implementation has not started. Confirmed decisions are recorded in the
[requirements and handoff](project-redesign.md); native/upstream evidence is in
the [source checks](project-redesign-research.md). The layout and implementation
sequence below are engineering proposals for review, not changes already made.

## Purpose and first-release scope

Agent Toolkit (`agent-toolkit`) manages shared AI application configuration,
optional reusable workflows, and selected upstream updates. Personal choices
live separately so another developer can adopt it without changing toolkit code.

The first release supports macOS and already-installed Claude Code, Codex CLI,
Gemini CLI, Pi, and both Antigravity CLI and IDE: five products, six interfaces.
Use documented native features, preserve useful differences, and explain gaps.
Do not install the applications or emulate missing capabilities for parity.

Preserve the existing managed global instructions, selected settings, and native
MCP registration where supported. Keep read-only zkfy integration optional and
enabled in the owner's personal configuration; load its retrieval instructions
only when enabled. Credentials and application-owned runtime/trust data remain
outside toolkit ownership. Repositories keep their own conventions and checks.

Four optional workflows are in scope: **plan**, **implement and verify**,
**review**, and **handoff**. Adapt selected ECC procedures with recorded source,
revision, license, and local modifications; handoff is toolkit-authored.
Exact imported revisions still need selection. The complete ECC plugin and a
managed project scaffold are outside this release's scope.

## How it should work

```text
Toolkit instructions, workflows, and defaults
             + external personal configuration
             → native configuration/discovery → verification

Official docs → reference mirrors → authored-guide drift report
ECC source   → inactive local review bundle → review/validation
             → explicit activation → verification/recovery
```

Personal configuration lives outside the checkout, proposed by default under
`~/.config/agent-toolkit/`. Ship small examples; keep exact schema and filenames
as implementation details. Track owned settings/paths and preserve unrelated
configuration. Settings are merged, not symlinked wholesale.

Automatic checks and reference refreshes are accepted. Behavioral changes are
staged outside active linked sources, with summaries, diffs, adaptation conflicts,
and validation results. User review precedes explicit activation. A failed fetch
retains the last valid content; a failed activation has a tested recovery path.
GitHub PR automation is not required. Scheduling and exact commands remain design
details; no new updater has been installed or enabled.

## Simple proposed structure and reading paths

```text
README.md    purpose, quick start, links to guides
AGENTS.md    concise maintainer map and relevant verification instructions
tools/       shared instructions, selected workflows, defaults, provenance
scripts/     apply, check, update, migration; native mappings where needed
examples/    personal configuration examples
docs/        explanation, three walkthroughs, ADRs, plans, reference mirrors
tests/       ownership, merges, discovery, updates, and migration checks
```

Use English for the maintained README, explanation, and walkthroughs. Keep a
short conceptual guide that explains what is managed, where authoritative
content lives, what belongs to the user, and how applications consume it.
Separate authored guides from generated reference mirrors. Retain historical
documents with their historical names and languages.

Humans follow README → conceptual guide → setup/handoff/update walkthrough.
AI tools follow concise AGENTS → relevant guide/task plan on demand. Task state
stays in project Markdown, with goal, decisions, progress, paths, checks, open
issues, and next action. Resuming requires those files, not the original chat or
interview plugin. Other checkouts/machines need the same revision via Git or copy.

## Implementation order

1. Inventory all six native interfaces, ownership, existing behavior, and live
   paths. Resolve supported settings/MCP surfaces and shared discovery conflicts.
2. Simplify sources and documentation; introduce external personal configuration
   and examples. Verify dry-run, idempotency, backups, and preservation.
3. Adapt and attribute the four workflows; install through native discovery and
   verify each interface. Demonstrate file-based cross-tool continuation.
4. Build reference refresh and inactive behavioral review bundles. Demonstrate a
   compatible update, an adaptation conflict, reviewed activation, and recovery.
5. Perform the full coordinated rename: hosted repository, checkout folders,
   toolkit-owned state/backup paths, maintained references, and installed links.
   Coordinate active agents/worktrees, repair Git registrations, and verify
   recovery. Prepare/test in isolation before moving active paths.
6. Complete the three walkthroughs and release checks; record runtime evidence
   for every supported interface and explicit native capability gaps.

## Acceptance and remaining technical work

The release must demonstrate all three agreed scenarios:

- **Setup:** an adopter supplies personal configuration, previews/applies/verifies
  selected integrations, repeats without changes, and understands missing
  prerequisites and optional vault behavior.
- **Continuation:** a fresh session in another tool resumes a real project task
  from durable Markdown state without chat history. Verify native discovery for
  all six interfaces separately; one handoff pair is not proof of every pairing.
- **Updates:** reference refresh and a reviewed behavioral update preserve local
  adaptations and personal choices, report conflicts, and support recovery.

Still to verify: installed versions, Antigravity IDE's supported settings controls,
exact settings/MCP mappings, shared skill/rule destinations, collision handling,
upstream pins, updater scheduling, and the current rename inventory/hosted-name
availability. These are implementation checks, not unapproved scope reductions.

## Resume and current work

Work in `plan/project-redesign` at `../ai-cli-workspace-planning`. Planning edits
are uncommitted and isolated from concurrent refactoring. No rename, installation,
configuration writes, upstream synchronization, or runtime checks have been done.
Document formatting and local-link checks passed.

Resume prompt:

> Read AGENTS.md, docs/plans/project-redesign-review.md, and the Handoff section
> in docs/plans/project-redesign.md. Preserve Q1–Q18. The interview is complete;
> review the proposed implementation plan and verify current repository state.
> Implementation has not been authorized in this planning task. Do not restart
> the interview or rename paths merely because they appear in the proposal.
