# Agent Toolkit — requirements and redesign plan

Status: **Requirements interview complete; consolidated proposal ready for review.**
Updated: 2026-10-12. Current step: review the proposal; implementation not started.

Start with the [consolidated redesign proposal](project-redesign-review.md).
This document retains the full decision history, evidence, and session handoff.

## Resume in any AI CLI

Work in branch `plan/project-redesign`, in the sibling checkout
`../ai-cli-workspace-planning`. The original checkout remains on
`refactor/global-config-scope` for the other AI. Keep planning edits isolated
until integration is deliberately coordinated.

Read the repository's `AGENTS.md`, the consolidated proposal, then this file's
handoff. Q1–Q18 are confirmed; do not restart the interview. Investigate technical
facts instead of asking the user to supply them. If a new material requirement
appears, ask one question with a recommendation and update this decision record.

This ordinary Markdown document holds the task state; no slash command, plugin,
private agent memory, or chat history is required. For agents that do not
automatically discover `AGENTS.md`, supply this prompt:

> Read AGENTS.md, docs/plans/project-redesign-review.md, and the Handoff section
> of docs/plans/project-redesign.md. Preserve Q1–Q18; the interview is complete.
> Review the proposal and verify current repository state. Implementation has
> not started or been authorized by this requirements-planning task.

Another machine or checkout needs the same document revision through Git or a
file copy. Uncommitted edits are available only in this checkout. Resumption
in another CLI has not yet been tested.

## Explicit user requirements

1. Choose a name that reflects the project's contents and purpose.
2. Explain what it does and how it works, for humans and AI readers.
3. Redesign a simple structure centered on the project's main purpose.
4. Define upstream updates, including Everything Claude Code (ECC), official
   AI tool documentation, and potentially plugins or skills.
5. Make this plan resumable across sessions and tools such as Codex, Pi, and
   Antigravity.
6. Combine personal setup management with a reusable toolkit for others, including
   selected upstream updates, project workflows, and shared skills (Q1: A + B).
   The initial workflows are selected in Q16; exact imported revisions remain open.
7. Other developers use the toolkit with their own configuration, without editing
   toolkit code (Q2: A). Personal model choices, vault binding, and plugin
   selections must be separable from reusable behavior.
8. Provide optional reusable procedures for planning, implementation, and review,
   with portable project plans and handoffs. Each repository owns its conventions,
   test commands, and choice of procedures; a managed project scaffold is outside
   the agreed scope (Q3: A).
9. The first release must configure and validate all five tools: Claude Code,
   Codex CLI, Gemini CLI, Pi, and Antigravity (Q4: B). Antigravity integration is
   required in this release, rather than deferred.
10. Support macOS only in the first release (Q5: A). Linux and native Windows
    support are outside this release.
11. Antigravity support includes both its terminal CLI and IDE in the first
    release (Q6: C). Both interfaces require configuration and verification.
12. Share intent using native features; preserve useful tool-specific features
    and document unavailable capabilities. Do not build emulation solely to
    achieve identical functionality across tools (Q7: A).
13. Adopt selected ECC skills or workflows, track their upstream source and
    revision, and record local adaptations. The toolkit owns maintenance of
    those adaptations (Q8: A); exact components remain to be selected.
14. Automatically check for upstream changes and refresh reference-only official
    docs. Prepare selected skill/workflow updates for review before activation;
    preserve local adaptations and surface conflicts (Q9: A).
15. Cover all three walkthroughs and acceptance scenarios: setting up shared
    configuration on a new Mac, continuing a project task in another tool, and
    adopting an upstream update while preserving personal choices (Q10: all).
16. Configure existing AI applications, detect missing prerequisites, and provide
    installation guidance. Installing/upgrading the applications themselves is
    outside the toolkit's responsibility (Q11: A).
17. Make vault access optional and enable the existing read-only zkfy integration
    in the owner's personal configuration. Others can supply a compatible vault
    or use the toolkit without one. Enable retrieval instructions together with
    the integration (Q12: A).
18. Use **Agent Toolkit** as the project name and **`agent-toolkit`** as its slug
    (Q13: A).
19. Perform a full, coordinated rename: hosted repository, existing checkout
    folders, toolkit-owned backup/state paths, maintained references, and installed
    links that point to the checkout (Q14: B). Include backups, worktree
    coordination, link repair, state migration, and recovery verification.
20. Store personal configuration outside the toolkit checkout, using
    `~/.config/agent-toolkit/` as the proposed default directory, with examples
    shipped in the repository (Q15: A). Users may version that configuration
    separately with their dotfiles.
21. Include four optional first-release workflows: plan, implement and verify,
    review, and handoff (Q16: A). Use repository-owned conventions and checks;
    these workflows are available individually, not mandated for every task.
22. Deliver staged behavioral updates as local review bundles containing readable
    summaries, diffs, conflicts, and validation results, with explicit activation
    (Q17: A). GitHub PR automation is not a first-release requirement.
23. Use English as the canonical language for the maintained README, conceptual
    explanation, and three walkthroughs (Q18: first option, equivalent to A).
    Upstream mirrors and historical documents retain their original languages.

Q4-Q6 establish five tools covering six interfaces on macOS, including both
Antigravity CLI and IDE. Supported features and native configuration surfaces
still need definition and verification. Q8 selects deliberate reuse of ECC
components; it does not select particular components or reinstall the full plugin.

## Current system — source evidence

Observed on 2026-10-08; live configuration was not validated:

| Responsibility | Source and mechanism |
|---|---|
| Global instructions | `tools/instructions/AGENTS.md`; `scripts/install-global-instructions.py` creates links to it. |
| Selected settings | `tools/settings/managed.json`; `scripts/apply-settings.py` merges managed keys into native files. |
| MCP registrations | `tools/mcp/servers.json`; `scripts/apply-mcp.py` invokes native commands for missing server names in Claude, Codex, and Gemini. |
| Vault access | External zkfy checkout; `scripts/install-vault-knowledge.py` binds a launcher and Claude/Pi skills. |
| Installation | `scripts/install.sh` orchestrates those steps for Claude, Codex, Gemini, and Pi. |
| Reference updates | `scripts/sync-cli-docs.sh` mirrors Claude, Codex, Gemini, and Antigravity docs. `.github/workflows/sync-cli-docs.yml` schedules weekly sync and commits/pushes changes. Pi is absent from that script. |

The configuration flow is: edit canonical source → apply through an installer →
inspect native configuration. Linked instructions can reflect edits immediately.
Reference documentation follows a separate fetch-and-commit flow.

[ADR-0005](../adr/0005-global-config-single-source.md) is the accepted baseline:
personal global configuration on macOS; retain native differences; retire
per-project generation; keep plugin choices outside repository ownership;
remove ECC; exclude Antigravity configuration. The new interview can explicitly
revisit these decisions. Antigravity reference docs already exist.

Observed issues to carry into design:

- Project docs broadly describe dry-run defaults, but `install.sh` initializes
  `DRY_RUN=0` and passes `--apply` unless `--dry-run` is supplied. The individual
  Python installers default to dry-run.
- Mirror paths are mixed: Codex/Gemini use `upstream/`; Claude/Antigravity are
  mirrored directly into their respective directories.
- Mirrored docs and historical ADRs alone do not establish current upstream
  capabilities or runtime behavior.
- `install.sh` skips vault integration without a zkfy checkout/binding, while
  `tools/instructions/AGENTS.md` directs substantive tasks to consult the vault
  and report a limitation if unavailable. The redesign must align installation
  and instruction behavior with the selected vault policy.

## Decisions and current question

| ID | State | Decision / rationale |
|---|---|---|
| R1 | User requirement | Persist a plan usable across sessions and AI CLIs. |
| P1 | Working method | Use this repository Markdown document with discovery links and a plain-text resume prompt. |
| Q1 | Confirmed by user | A + B: personal AI setup management with selected upstream updates, plus a reusable toolkit for others including project workflows and shared skills. Q16 selects the initial workflows; exact imported revisions remain open. |
| Q2 | Confirmed by user | A: other developers use the toolkit with their own configuration, without editing its code. Keep personal choices separate from reusable behavior. |
| Q3 | Confirmed by user | A: optional reusable procedures and portable plans/handoffs; each repository owns its conventions and test commands. No managed project scaffold. The user said to follow the recommendation for Q3. |
| Q4 | Confirmed by user | B: tested installation support for Claude Code, Codex CLI, Gemini CLI, Pi, and Antigravity in the first release. |
| Q5 | Confirmed by user | A: macOS only for the first release; Linux and native Windows are outside this release. |
| Q6 | Confirmed by user | C: configure and verify both Antigravity terminal CLI and IDE in the first release. |
| Q7 | Confirmed by user | A: shared intent through native features, preserving useful tool-specific behavior and documenting gaps; no emulation for full parity. |
| Q8 | Confirmed by user | A: adopt selected ECC skills/workflows, track source revisions and local adaptations, and maintain the adaptations. |
| Q9 | Confirmed by user | A: automatic checks and reference-document refreshes; prepare skill/workflow update diffs for review before activation. |
| Q10 | Confirmed by user | All three: setup, cross-tool continuation, and upstream updates. The user replied “all agreeed”; no exclusive priority was selected. |
| Q11 | Confirmed by user | A: configure existing applications, detect missing prerequisites, and provide guidance; application installation/upgrades remain external. |
| Q12 | Confirmed by user | A: optional read-only vault integration, enabled in the owner's personal configuration; other adopters can omit it. |
| Q13 | Confirmed by user | A: Agent Toolkit, with slug `agent-toolkit`. |
| Q14 | Confirmed by user | B: full coordinated rename, including hosted repository, checkout folders, toolkit state paths, and affected installed links. |
| Q15 | Confirmed by user | A: personal configuration outside the checkout; repository contains examples. |
| Q16 | Confirmed by user | A: four optional workflows—plan, implement and verify, review, and handoff. Native documentation and candidate ECC sources have been checked; runtime validation remains open. |
| Q17 | Confirmed by user | A: local staged review bundles, with readable reports/diffs and explicit activation. GitHub PR automation is not required for this release. |
| Q18 | Confirmed by user | First option (A): English as the canonical language for README, explanation, and walkthroughs. The user answered “1”. |

**Q1 resolved: the user selected A + B.**

Agreed direction: maintain the owner's personal AI coding setup and provide a
reusable toolkit for other developers, including selected upstream updates,
project workflows, and shared skills. The user did not yet specify a priority
between personal use and reuse or a distribution mechanism. Q16 subsequently
selects the initial workflows. The earlier global-configuration-only boundary is being expanded;
ADR-0005 remains the description of the existing implementation.

**Q2 resolved: the user selected A.**

Other developers supply their own configuration without editing toolkit code.
Reusable behavior and personal choices must be distinct. The recommendation's
rationale was easier reuse and fewer conflicts between personal customization
and toolkit updates; the user confirmed the option without adding constraints.
No package manager, profile engine, configuration format, or layout is selected.

**Q3 resolved: the user accepted recommendation A.**

Provide optional reusable skills or instructions for planning, implementation,
and review, together with portable project plans and handoffs. Individual
repositories own their conventions, test commands, and choice of procedures.
The recommendation's rationale was a smaller, adaptable toolkit that preserves
ADR-0005's retirement of managed project scaffolding. Q16 subsequently selects
four workflows; exact packaging and file formats remain open. Acceptance applies to Q3; it does not
pre-approve recommendations on future questions.

**Q4 resolved: the user selected B, all five from the first release.**

Claude Code, Codex CLI, Gemini CLI, Pi, and Antigravity all require installation
support and validation in the first release. This expands the existing four-tool
installer scope. Antigravity's intended interface and native configuration need
verification before implementation. The choice establishes tool coverage, not
identical feature support across tools, and does not establish OS coverage.
The user chose B over the recommendation to defer Antigravity; retain that choice.

**Q5 resolved: the user selected A, macOS only.**

Keep the existing macOS platform scope for the first release, while adding
reusable configuration and support for all five tools. Linux and native Windows
are outside this release. Current native support and runtime behavior for the
selected integrations must still be verified; this is a target requirement.

**Q6 resolved: the user selected C, both CLI and IDE.**

Antigravity terminal CLI and IDE are both first-release requirements. Together
with Claude Code, Codex CLI, Gemini CLI, and Pi, this means five tools covering
six interfaces on macOS. Do not silently defer either Antigravity interface.
Configuration ownership and runtime validation must account for both; inspect
current native surfaces before deciding whether they share implementation.

Local evidence: `docs/agy/INDEX.md`, `cli-install.md`, and `gcli-migration.md`
describe the terminal CLI. ADR-0005 separately excluded Antigravity IDE
configuration. These references establish repository history, not current native
support. Current official documentation and runtime verification remain required.

**Q7 resolved: the user selected A, shared intent using native features.**

Use each tool's native configuration and supported features to deliver shared
instructions, selected procedures, and portable plans. Preserve useful native
features and clearly document gaps. No emulation solely to force full parity.
This retains ADR-0005's native-differences principle while expanding coverage to
both Antigravity interfaces. Current feature availability must still be checked.

**Q8 resolved: the user selected A, selected ECC skills and workflows.**

Choose specific ECC components to adopt, retain their upstream source and
revision, and record local adaptations. This keeps the imported scope deliberate;
the toolkit maintains compatibility and updates for its adaptations. The exact
repository, component list, and license/attribution requirements still need
verification. This does not select or reinstall the entire ECC plugin, and does
not yet establish update cadence or automatic activation.

**Q9 resolved: the user selected A, automatic checks with reviewed activation.**

Automatically refresh reference-only official documentation and detect upstream
changes. Prepare selected skill/workflow update diffs and compatibility findings
for review before activation. Preserve local adaptations and report conflicts.
Reference refreshes do not rewrite authored explanations or local adaptations.
Keep prepared behavioral updates outside active sources until activation: current
linked global instructions can affect live sessions immediately.

This is the user's chosen update policy. Cadence, diff delivery, validation,
conflict handling, and rollback remain implementation details to resolve. No
automation has been implemented or enabled during this interview.

**Q10 resolved: the user agreed to all three scenarios.**

The reply “all agreeed” is recorded as acceptance of all three offered workflows:

1. Set up shared configuration on a new Mac: choose tools and personal settings,
   apply selected instructions/components, and verify what each tool consumes.
2. Continue a project task in another tool: preserve the plan, decisions, and
   progress, then resume from that state in a different tool/session.
3. Adopt an upstream update: detect changes, understand their effect, review and
   apply the adaptation, and verify that personal choices survive.

All three need human/AI walkthroughs and acceptance evidence. No exclusive
priority was chosen. A proposed presentation order is setup → handoff → updates;
that ordering is an editorial choice, not a reduced feature commitment.
Agreement to Q10 does not pre-approve recommendations on subsequent questions.

**Q11 resolved: the user selected A, configure existing applications.**

Detect selected AI applications, explain missing prerequisites, and manage their
shared configuration and selected components. Application installation and
upgrades remain with their own supported installers. The setup walkthrough must
make this prerequisite clear. Support and validation for all five tools/six
interfaces remain required; selected skills/workflows and reference updates
remain within Q8-Q9's scope.

**Q12 resolved: the user selected A, optional vault integration.**

Retain read-only zkfy access in the owner's personal configuration. Other adopters
can configure a compatible vault or use the toolkit without one. Couple retrieval
instructions with enabling the integration so configurations without a vault do
not inherit a mandatory vault dependency. Preserve the owner's existing retrieval
behavior and read-only boundaries. A generic knowledge-provider framework is not
implied, and the current session's retrieval instructions remain in force.

**Q13 resolved: the user selected A, Agent Toolkit (`agent-toolkit`).**

The name covers reusable configuration, skills/workflows, and upstream updates
across CLI and IDE interfaces. It is the accepted project identity; namespace
availability has not been checked, and no repository or installed path has been
renamed. The concrete migration is defined by Q14 and the later implementation
plan. Planning continues in the existing isolated worktree.

**Q14 resolved: the user selected B, a full coordinated rename.**

The migration includes the hosted repository, existing checkout folders,
toolkit-owned backup/state paths, maintained references, and installed links
pointing into the checkout. Coordinate active worktrees and preserve other
agents' work before moving paths. Back up existing configuration/state, migrate
without overwriting unrelated data, repair affected links and Git worktree
registrations, and verify recovery as well as the resulting installation.

Current source uses `.local/state/ai-cli-workspace/` for settings and instruction
backups; these become part of the migration to the new toolkit namespace.
Native application path names and external zkfy ownership remain their own;
update toolkit references rather than renaming unrelated application directories.
Historical ADRs retain historical names. Check the hosted repository owner,
new-name availability, and affected links when preparing the migration.
The user chose B over staged migration; do not silently defer path migration.
No rename is executed during this requirements interview.

**Q15 resolved: the user selected A, outside the toolkit checkout.**

Use a separate user configuration directory, proposed as
`~/.config/agent-toolkit/`, and ship minimal examples in the toolkit repository.
Users may version personal configuration with their dotfiles. A new-Mac setup
must explain how to transfer this file as well as obtain toolkit code. No
credentials belong in the toolkit; exact schema and filename remain design
details. This establishes a storage boundary without requiring a profile engine.

**Q16 resolved: the user selected A, all four optional workflows.**

The confirmed first-release set is:

1. **Plan:** clarify requirements, inspect the project, and save an actionable plan.
2. **Implement and verify:** follow the agreed scope, make focused changes, and
   run the consuming repository's relevant checks.
3. **Review:** inspect changes and surrounding context, then report prioritized,
   actionable findings.
4. **Handoff:** save decisions, progress, paths, checks, and the next action so
   another session/tool can continue.

Four covers the agreed task lifecycle without adding a large catalog to
maintain. Each remains optional; this is not a mandatory four-step process for
every edit. The user's selection confirms workflow scope, not untested native
integration or exact imported source revisions.

Candidate inputs are ECC's planner, verification-loop, and code-reviewer, adapted
to remove fixed model/tool choices and blanket mandates. The implementation
procedure and handoff convention include toolkit-authored content. See the
[source checks and adaptation notes](project-redesign-research.md) for primary
references, native discovery paths, and unresolved compatibility details.
No component has been imported or activated.

**Q17 resolved: the user selected A, local review bundles.**

A check prepares an inactive snapshot
and a readable summary of changed sources, local adaptations, conflicts, diffs,
and validation results. A user or AI CLI can read the same bundle; an explicit
activation step applies reviewed changes. Keep staged content outside active
linked sources, as required by Q9. Exact commands and paths remain design details.

Local bundles keep the toolkit usable without a hosting/account dependency and
give every AI CLI the same file-based review material. GitHub PR automation is
outside the required first-release scope; this does not change the hosted rename
requirement. Q9's automatic checks and reference refreshes remain accepted.
No update automation or bundle-generation code has been implemented.

**Q18 resolved: the user selected the first option, English.**

Use English for the maintained README, conceptual explanation, and three
walkthroughs. The user's “1” selects the first listed option, equivalent to A.
Keep one canonical guide set; maintained bilingual guides are not required.

The current repository mixes English entry material with Chinese research docs.
This question applies to maintained redesign guides, not translation of upstream
mirrors or historical archives. Language does not change the CLI-neutral resume
mechanism, ownership boundaries, or the accepted workflow scope.

## Working structure proposal

This is a draft to make the design concrete, not an accepted final layout.
Keep the existing small source/script separation and make ownership explicit:

```text
README.md     purpose, scope, quick start, links to walkthroughs
AGENTS.md     concise repository map and task/validation instructions
tools/        shared instructions, selected skills, small defaults, upstream provenance
scripts/      apply, check, update; native differences handled here
examples/     minimal personal configuration examples
docs/         explanation, walkthroughs, decisions, plans, reference mirrors
tests/        meaningful installer, update, and migration verification
```

Personal configuration lives outside the checkout per Q15. Proposed toolkit state uses
the renamed `~/.local/state/agent-toolkit/` namespace; Q14 requires migration
from the old namespace. Exact source filenames and entry commands remain open.

Human reading path: README → concise explanation of sources and destinations →
the setup, handoff, and update walkthroughs. AI reading path: short AGENTS →
relevant guide or task plan on demand. Consolidate overlapping overview material
instead of maintaining multiple competing descriptions of the current system.
Keep authored documentation separate from generated reference mirrors, proposed
under `docs/reference/`, so synchronization only replaces its owned content.

Proposed configuration flow: shared toolkit content + personal choices → native
tool configuration → verification. Proposed update flow: fetch reference docs or
stage component changes → show changes/conflicts → review behavioral changes →
activate and verify. Preserve the chosen native-feature boundaries; do not build
a general plugin framework or feature-emulation layer merely to organize files.

This proposal changes only this planning document. No directories, runtime
configuration, or implementation have been created from the draft.

## Draft implementation sequence and acceptance

This sequence is proposed for review; it does not authorize implementation during
the interview. It uses the confirmed scope and the saved source checks.

| Step | Concrete deliverable | Completion evidence |
|---|---|---|
| 1. Inventory and explain | Map owned sources, native destinations, current behavior, personal choices, and all six interfaces. Resolve supported settings/MCP surfaces, including IDE controls. Draft a short purpose/flow explanation. | Distinguish documented support, runtime observations, and native-only/manual controls. Identify collisions, masked instructions, and unsupported mappings before writes. |
| 2. Simplify configuration and structure | External personal configuration with examples; clear source/script/documentation ownership; concise human/AI entry points; separated reference mirrors. Retain current managed instructions, settings, MCP, and optional vault behavior unless a change is explicitly justified. | An adopter can choose tools and personal values without editing toolkit code. Dry-run shows intended changes; repeated apply is idempotent; unrelated configuration survives. |
| 3. Add selected workflows | Adapt and attribute revision-pinned ECC inputs; author the implementation and handoff conventions; expose the four optional workflows through native discovery. | Each of the six interfaces discovers its selected workflows. Shared destinations and name collisions are handled. A consuming repository supplies its own conventions/checks. |
| 4. Add reviewed updates | Separate reference refreshes from behavioral changes; record provenance; generate inactive local review bundles; validate and explicitly activate reviewed versions with recovery. | Compatible updates and local adaptation conflicts are both demonstrated. Failed fetches retain the previous snapshot; unreviewed changes do not affect active sources; personal choices survive activation and recovery. |
| 5. Execute coordinated rename | Prepare a full migration inventory and recovery record; coordinate active agents/worktrees; rename the hosted repo and checkout folders; migrate owned state; repair Git registrations and installed links. | All old/new paths and hosted-name availability checked. Existing work is preserved; new paths and recovery work. Historical names and external/native namespaces retain their proper ownership. |
| 6. Complete comprehension and release checks | Final README, concise architecture/source-destination guide, three walkthroughs, capability matrix, and implementation handoff. | All three scenarios below pass; all six interfaces have runtime evidence or a clearly documented native capability gap. Generated files alone do not count as runtime validation. |

Build and test the changes in isolation before step 5 moves active paths.
Step 5 remains a full coordinated rename under Q14, not a partial release or
silent deferral. Prepare the exact migration operations and current worktree
inventory immediately before execution because other agents may change them.

The conceptual explanation must let a human or AI answer: what the toolkit
manages, where the authoritative content lives, which choices belong to the
user, what each application consumes, and how an update becomes active.
Detailed rules and transient task state stay in on-demand files rather than
expanding globally loaded instructions.

Accepted scenarios, with proposed concrete evidence:

1. **New-Mac setup:** with applications already installed, supply external
   personal configuration; preview, apply, and verify selected integrations;
   repeat without changes. Demonstrate missing-prerequisite reporting and both
   vault-enabled and vault-disabled configurations without overwriting user data.
2. **Cross-tool continuation:** one tool records a project task's goal, decisions,
   changed paths, check results, and next action. A fresh session in another tool
   resumes from those files without the original chat or interview plugin.
   Verify native workflow discovery separately for every supported interface;
   do not claim one handoff pair proves all pairwise combinations.
3. **Upstream update:** detect changes, refresh reference-only material, prepare a
   behavioral update bundle, inspect the diff and adaptation conflict, resolve
   and validate it, then explicitly activate. Demonstrate recovery and unchanged
   personal choices. Broken/moved sources must preserve the last valid snapshot.

Tests should cover meaningful ownership, merge, collision, idempotency, update,
and migration behavior. Use isolated fixture directories for automated write
tests and separately record native runtime checks. No tests or installations
for this implementation sequence have run during planning.

## Remaining technical checks

No unanswered interview question is currently pending. The proposed structure,
implementation sequence, and acceptance evidence are consolidated for review.
During implementation, resolve exact configuration/schema details, ownership and
shared-path collisions, source pins, scheduling, runtime checks, and the current
rename inventory. Revisit the user only if evidence materially changes scope.

Bounded
[native and upstream source checks](project-redesign-research.md) are complete
for the initial workflow proposal. Exact settings/MCP mapping, installed-version
behavior, and runtime compatibility still need verification. Consult current
official sources when remaining decisions depend on native support.

## Vault evidence and synthesis

These sections were read through the read-only vault launcher:

- `333.ai/llm/AI-LLM-Context-Management-Patterns.md#Offload to the Filesystem`
  describes durable file-backed context. Application here: keep plan state local.
- `333.ai/agents/AI-Agent-Memory-Governance.md#Memory as Reasoning` distinguishes
  facts, inferences, transient context, and hypotheses. Application here: record
  accepted answers separately from recommendations.
- `333.ai/methodology/AI-Portable-Harness-Design.md#Memory Gradient` distinguishes
  global and project-local context. Application here: avoid putting this
  project's transient plan in shared global instructions.
- That note's `#Mental Model` describes a broader memory/dev/pipe toolkit; this
  differs from ADR-0005's scope and has not been adopted here.
- `111.cs/programming/design-pattern/CS-Design-Pattern-Adapter.md#Intent`
  describes translating an existing interface into the client's expected
  interface. Application here: keep native configuration handling behind the
  small setup/update operations, without requiring identical feature support.
- `111.cs/system-design/performance/abseil-tips/cs-performance-Abseil-Tip-52-Configuration-Knobs-Considered-Harmful.md#The Problem with Knobs`
  discusses stale overrides and the testing cost of configuration flags.
  Application here: expose the personal choices Q2 requires without adding a
  generic profile/framework configuration surface. This is synthesis from a
  performance-oriented note, not a vault prescription for the directory layout.

These applications are synthesis, not additional user requirements. Two focused
upstream/ECC searches did not establish an applicable update lifecycle; no update
design is attributed to search excerpts.

## Handoff

- Completed: inspected project entry docs, ADR-0005, installation orchestration,
  relevant settings/MCP code, documentation sync script/workflow, and the vault
  sections above; located and read the requested `grill-me` skill. Checked primary
  native skill/instruction documentation and candidate ECC component sources;
  saved findings in `project-redesign-research.md`.
- Current step: Q1 = A + B, Q2 = A, Q3 = A, Q4 = B, Q5 = A, Q6 = C,
  Q7 = A, Q8 = A, Q9 = A, Q10 = all, Q11 = A, Q12 = A, Q13 = A, Q14 = B,
  Q15 = A, Q16 = A, Q17 = A, and Q18 = first option (A) recorded. Interview complete;
  the consolidated proposal is ready for review. Structure, exact update mechanics,
  and implementation details remain proposals; implementation has not started.
- Changes: this document, its research and consolidated-review companions, and discovery links
  in `AGENTS.md`, `README.md`, and `docs/INDEX.md`; no runtime implementation changes.
- Isolation: moved only this task's four documents to the new branch/worktree;
  removed their additions from the original checkout. Existing changes to
  `.serena/project.yml` remain in the original checkout and were byte-verified
  unchanged during the move.
- Checks: planning document formatting and relative links passed. A whole-tree
  `git diff --check` reported existing trailing whitespace in `.serena/project.yml`;
  that unrelated file was left untouched. No installer, doc sync, live
  healthcheck, or runtime test executed for this planning task.
- Next: review `project-redesign-review.md`. Before any later implementation,
  verify current branch/worktree state and coordinate with the concurrent agent.
  Do not re-ask confirmed scope choices or treat the proposal as completed work.
