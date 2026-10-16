# Project redesign — requirements and plan

Status: **Round 2 interview in progress (Q17 onward, 2026-10-16); Q1–Q16 stand.**
Updated: 2026-10-16. Current question: Q26 (see "Round 2"). Implementation not
started; round 2's evidence partly answers research items R-a to R-d.

## Resume in any AI CLI

Read the repository's `AGENTS.md`, then this file. Ask one question at a time,
with a recommended answer and tradeoff. Keep each question short, in plain text,
with numbered options. The user may combine options (e.g. "1 + 3"), so don't use
single-choice question tools. Investigate repository facts instead of
asking the user to supply them. After each answer, update the decisions,
rationale, unresolved dependencies, and current question here.

This ordinary Markdown document holds the task state; no slash command, plugin,
private agent memory, or chat history is required. For agents that do not
automatically discover `AGENTS.md`, supply this prompt:

> Read AGENTS.md and docs/plans/project-redesign.md. Resume from the current
> step, one question at a time, recommending an answer and explaining the
> tradeoff. Preserve confirmed decisions and update the plan after each answer.

This document is committed on local branch `claude/project-redesign` but not
pushed. Another checkout on this Mac can read it with
`git show claude/project-redesign:docs/plans/project-redesign.md`; another
machine needs a push (ask the user first) or a file copy. Resumption in another
CLI has not yet been tested.

## Where this copy lives

- Branch `claude/project-redesign`, in the worktree `../ai-cli-workspace-claude`
  (a sibling of the original checkout). It starts from `refactor/global-config-scope`
  at `fab3fb5`.
- Forked on 2026-10-08 from the plan another AI started in the original
  checkout. That AI now works in its own worktree, `../ai-cli-workspace-planning`,
  on branch `plan/project-redesign`, and the original checkout is clean again.
  This copy has diverged from that one; see "Conflicts with the other AI's plan".
- Never change the original checkout from here. All four CLIs' global
  instructions link to its `tools/instructions/AGENTS.md`. Renaming or moving
  that file, or switching branches there, changes or breaks the live
  instructions immediately.

## Explicit user requirements

1. Choose a name that reflects the project's contents and purpose.
2. Explain what it does and how it works, for humans and AI readers.
3. Redesign a simple structure centered on the project's main purpose.
4. Define upstream updates, including Everything Claude Code (ECC), official
   AI tool documentation, and potentially plugins or skills.
5. Make this plan resumable across sessions and tools such as Codex, Pi, and
   Antigravity.

Q2 settles the installer targets, and Q3 and Q4 settle ECC's role: it is a
catalog to pick from and is never reinstalled wholesale.

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

How it works today (the explanation given to the user for goal 2; it seeds
`docs/how-it-works.md`):

```text
YOU EDIT (tools/)          APPLIED BY (install.sh runs all four)       LANDS IN
instructions/AGENTS.md ─► install-global-instructions.py (symlink) ─► each CLI's global instructions
settings/managed.json  ─► apply-settings.py (merge listed keys)    ─► settings.json / config.toml
mcp/servers.json       ─► apply-mcp.py (native `mcp add`)          ─► Claude, Codex, Gemini (Pi: no MCP)
zkfy repo (external)   ─► install-vault-knowledge.py (links)       ─► vault-query skill (Claude, Pi)
                          healthcheck.sh checks the live state
SEPARATE JOB: weekly GitHub Action ─► sync-cli-docs.sh ─► docs/<cli>/ copies of official docs
```

The configuration flow is: edit canonical source → apply through an installer →
inspect native configuration. Linked instructions can reflect edits immediately.
Reference documentation follows a separate fetch-and-commit flow. Of 492 tracked
files, 425 (86%) are the docs mirror; scripts, tests and tools are 15 files.

[ADR-0005](../adr/0005-global-config-single-source.md) is the accepted baseline:
personal global configuration on macOS; retain native differences; retire
per-project generation; keep plugin choices outside repository ownership;
remove ECC; exclude Antigravity configuration. This interview revisits parts of
it: Gemini CLI is dropped, Antigravity is added, ECC becomes a pick-from
catalog, and the repo gains a skills plugin. ADR-0006 will record that.

Observed issues to carry into design:

- Project docs broadly describe dry-run defaults, but `install.sh` initializes
  `DRY_RUN=0` and passes `--apply` unless `--dry-run` is supplied. The individual
  Python installers default to dry-run.
- Mirror paths are mixed: Codex/Gemini use `upstream/`; Claude/Antigravity are
  mirrored directly into their respective directories.
- Mirrored docs and historical ADRs alone do not establish current upstream
  capabilities or runtime behavior.
- Branch state: the ADR-0005 work sits on local-only branch
  `refactor/global-config-scope`, 16 commits ahead of `origin/main` and 10 behind
  (weekly doc syncs). A simulated merge (`git merge-tree`) reports 112 conflicts,
  all in regenerable mirror pages. Neither `origin/main` nor local `main` has
  `tools/instructions/AGENTS.md`, so checking out `main` in the live checkout
  would dangle all four live instruction links. Merge `main` into the branch,
  or use a worktree.
- Rename hazard: the live instruction links are absolute paths into the
  original checkout. Moving or renaming it leaves them dangling, and
  `install-global-instructions.py` then refuses until `--replace-instructions`,
  because it treats a non-matching link as unknown instructions (from reading the
  code; not executed). Other name- or path-keyed state:
  `~/.local/state/ai-cli-workspace/`, Claude's per-project memory directory, the
  sync script's user agent, `.serena/project.yml`, and doc titles.
- `template/prompts.md` is unsafe, not only stale. Its opening prompt runs
  `printf … > ~/.claude/CLAUDE.md`, which now writes through the link and would
  overwrite the shared source for every CLI.
- Stale or contradictory docs:
  - `docs/global-instructions.md` still says Python 3.8+, says the repo-root
    files are generated, and mentions a session-start hook.
  - `CONTEXT.md` lists no skills folder for Codex or Gemini, but their mirrored
    docs describe one.
  - The sync script and workflow cite a missing
    `docs/inventory/crawler-tech-research-2026-06-07.md`.
- Antigravity: `agy` 1.0.4 is on PATH but has never been launched. Its mirrored
  docs say it reads `~/.gemini/GEMINI.md`, so it probably already gets the shared
  instructions (not checked at runtime). Its settings, MCP (`mcp_config.json`),
  plugins and skills live under `~/.gemini/antigravity-cli/`, which does not
  exist on this Mac yet. The Antigravity IDE was installed on 2026-09-14, has one
  crash log from 2026-09-15, and has no saved conversations.
- Last use per tool (newest session file, 2026-10-08):

  | Tool | Last used |
  |---|---|
  | Claude, Codex | 2026-10-08 |
  | Pi | 2026-10-05 |
  | Antigravity IDE | 2026-09-15 |
  | Gemini CLI | 2026-05-25 |

- User-level skill folders, per the branch's mirrored docs (10 syncs stale; not
  checked at runtime):

  | CLI | Folder |
  |---|---|
  | Claude | `~/.claude/skills/` |
  | Codex | `~/.agents/skills/` |
  | Gemini | `~/.gemini/skills/` or `~/.agents/skills/` |
  | agy | `~/.gemini/antigravity-cli/skills/` |
  | Pi | `~/.pi/agent/skills/` |

- The docs-sync workflow runs weekly on `main` (latest success 2026-10-05). It
  commits with `git add -A` and pushes straight to `main`; there is no review
  step.
- Licenses (checked 2026-10-08): `mattpocock/skills` and ECC are MIT. In
  `anthropics/skills`, 14 skills are Apache-2.0, but `pdf`, `docx`, `pptx` and
  `xlsx` are "All rights reserved" and must not be redistributed. The
  `ai-cli-workspace` GitHub repo is PRIVATE, although its README says MIT. A
  pattern scan of all 62 commits found no token-like strings (not exhaustive).

## Decisions

| ID | State | Decision / rationale |
|---|---|---|
| R1 | User requirement | Persist a plan usable across sessions and AI CLIs. |
| P1 | Working method | Use this repository Markdown document with discovery links and a plain-text resume prompt. |
| Q1 | Decided (user) | Personal setup manager. Global config (instructions, settings, MCP, vault binding) stays personal. The repo also holds a small curated set of skills. ECC and the official docs are sources you review and pick from; nothing applies to a live CLI automatically. |
| Q1a | Decided (user) | "For others" means the curated skills ship as a plugin, installed and updated with each CLI's own plugin command (zkfy is the precedent), wherever a CLI supports plugins. You use the same plugin on every machine. The config layer is not packaged for others. |
| Q2 | Decided (user) | Targets: Claude Code, Codex, Pi, Antigravity. Gemini CLI is dropped (last used 2026-05-25). The installers stop managing it and leave its files alone. `~/.gemini/GEMINI.md` stays linked because Antigravity reads it. Local models are a later item. |
| Q2a | Decided (user) | Antigravity means both the CLI (`agy`, config under `~/.gemini/antigravity-cli/`) and the IDE (editor-style settings in `~/Library/Application Support/Antigravity IDE/User/settings.json`, data in `~/.gemini/antigravity-ide/`). The IDE's own surfaces are research item R-b. |
| Q3 | Decided (user) | Upstream sources: (1) official docs for the four targets: Claude Code, Codex, Pi, Antigravity CLI and IDE (changelogs come with the docs; Gemini CLI docs are dropped); (2) ECC (`affaan-m/everything-claude-code`) as a catalog to pick from; (3) other skill collections, chosen in Q3a. |
| Q3a | Decided (user) | Other skill collections: `anthropics/skills` and `mattpocock/skills` (the source of `grill-me` and `grill-with-docs`). |
| Q4 | Decided (user) | A picked skill is copied into the plugin and pinned. A lock entry records the source repo, path, commit and license. Upstream changes arrive as a diff for review, local edits are allowed, and the license file travels with the skill. Recommended with this option and not objected to: copy only MIT or Apache skills, never the four "All rights reserved" Anthropic skills (they stay in claude.ai sync). |
| Q5 | Decided (user) | Keep the repo private for now ("for this stage"). There is one repo, and the skills plugin lives inside it. You install and update it on your own machines with each CLI's plugin command (installing your private `lang-packs` repo already works this way); others need an invitation. Going public later should be a visibility switch, not a migration: keep the license check, no secrets and no machine paths. |
| Q6 | Decided (user) | The official-docs mirror stays in this repo, in one clearly separated folder (`upstream/`). Only the sync writes to it, so git history shows what changed upstream each week, and AI tools read it as ordinary files. |
| Q7 | Decided (user) | A weekly CI job opens a pull request instead of pushing to `main`. The PR holds the refreshed docs plus a skill-source report: changes to picked skills appear as diffs, and new upstream skills are only listed, never added. You review and merge. The same update can run locally on demand. This resolves the vault note's open question about the doc-refresh trigger. |
| Q8 | Decided (user) | The repo is renamed `ai-dotfiles`: a personal config repo whose files are linked into your home folder, now also carrying your skills. "cli" no longer fits because the Antigravity IDE is in scope, and "workspace" suggested a place you work in. The name is free on the account (checked 2026-10-08). |
| Q8a | Decided (user) | The skills plugin is also called `ai-dotfiles`, one name for repo and plugin. In Claude its skills appear as `ai-dotfiles:<skill>`. It is one plugin, not split into memory/dev/pipe plugins. |
| Q9 | Decided (user) | Layout approved with today's `tools/` name kept, and its inner paths unchanged. New top-level folders: `skills/` (the plugin) and `upstream/` (the docs mirror). See "Layout". |
| Q9a | Decided (user) | The plugin carries skills only: no agents, hooks or rule files. Commands come along as skills, and rules stay in `tools/instructions/AGENTS.md`. Skills are the only component all four tools load the same way. An `agents/` folder can be added next to `skills/` later if a specific need appears. |
| Q10 | Decided (user) | Three explanation files. `README.md` is for humans: what it is, setup, and everyday tasks such as changing instructions, adding a setting, adding or updating a skill, and reviewing the weekly update PR. `AGENTS.md` is for AI: a short map and the rules, and it is read at the start of every session. `docs/how-it-works.md` serves both: the full mechanism, where each tool keeps things, the update flow, the safety rules and a glossary. The other seven explanation files (`CONTEXT.md`, `tools/README.md`, `docs/INDEX.md`, `docs/global-instructions.md`, and the three `CAPABILITIES.md` files) are merged into these or removed (see "Cleanup list"). |
| Q11 | Decided (user) | All docs in English only, including the README (its Traditional Chinese summary line goes). |
| Q12 | Decided (user) | Cleanup list approved, with the research docs deleted rather than archived. See "Cleanup list". |
| Q13 | Decided (user) | Starting skills: `grill-me` and the `grilling` skill it calls (from `mattpocock/skills`, MIT), plus `skill-creator` (from `anthropics/skills`, Apache-2.0). The local copy of `grilling` is edited to ask one question per message, in plain text with numbered options and combinable answers, because upstream now asks a whole round at once. The local copy of `grill-me` also needs an edit: upstream's whole body is "Call the Skill tool with 'grilling'", and Codex, Pi and Antigravity have no Skill tool. Reword it to load or follow the `grilling` skill by name, or inline it. Claude will also still show the claude.ai-synced `grill-me` and `skill-creator`; removing those copies is optional. |
| Q14 | Decided (user) | Reconciled with the other plan: this plan's "for others" applies now (skills plugin only, config personal, repo private). The other plan's toolkit, which others run with their own configuration, becomes a later stage. Keep personal values in one place (`tools/settings/managed.json`, no machine paths in scripts) so they can be separated later. |
| Q15 | Decided (user) | Reconciled with the other plan: Gemini CLI is dropped (confirms Q2). It can return in the later toolkit stage if other developers need it. |
| Q16 | Decided (user) | Commit this plan on `claude/project-redesign` and stop. Implementation is a separate, later task that any AI can resume from this file. Before it starts: do research items R-a to R-d, confirm agent defaults A1–A6, and retire the other AI's diverging plan copy. Pushing was not requested: this branch sits on 16 unpushed `refactor/global-config-scope` commits, so pushing it would publish those too and needs its own confirmation. |

## Round 2 — five considerations (2026-10-16)

The user asked for a new interview to complete the workspace around five
considerations: tools, rules (steering), memory (docs), portability to other
environments, and staying in sync with the latest docs, "based on my using ai
essential". That is read as their own design note
`333.ai/methodology/AI-Portable-Harness-Design.md` (the `ai-to-go`
memory/dev/pipe spine; the vault hub labels it "Own design (ai-to-go)").
Q1–Q16 stand unless a row below says otherwise. Same method: one question at a
time, numbered combinable options, a recommendation and its tradeoff.

### New evidence (checked 2026-10-16 against mirrored docs, installed CLIs and git)

- Docs sync: `developers.openai.com/llms.txt` is now a hub, and the Codex index
  moved (now `learn.chatgpt.com/docs/llms.txt`). `sync_codex` fails closed only
  at 0 pages, so the 2026-08-10 and 2026-10-12 syncs each cut
  `docs/codex/upstream/` to 2–3 pages and pushed to `main`. The last full
  snapshot is `be14c14`. Claude has the same 0-page floor; Antigravity discovery
  covers only `cli-*` pages (no MCP, skills, rules or hooks pages); Pi is not
  mirrored.
- Pi 1.0.2 (Homebrew, `@earendil-works/pi-coding-agent`) has built-in MCP
  (`pi mcp add`, `~/.pi/agent/mcp.json`), reads skills from `~/.agents/skills`
  as well as `~/.pi/agent/skills`, and installs packages with `pi install git:…`
  (skills, prompts, extensions, themes). This answers R-a for Pi and changes A3.
  Its docs are in `earendil-works/pi`, `packages/coding-agent/docs/` (index
  `docs.json`).
- Codex 0.161: user skills live in `~/.agents/skills`; custom prompts are
  deprecated in favor of skills; plugins exist (`.codex-plugin/plugin.json`,
  `codex plugin marketplace add`); memories are experimental and off.
- Claude Code 2.1.301 does not read `.agents/`. A plugin auto-installs on a new
  Mac when user settings declare `extraKnownMarketplaces` and `enabledPlugins`;
  omitting `version` makes each commit a version. It reads project `AGENTS.md`
  natively (since 2.1.277), so per-project `CLAUDE.md` symlinks are optional.
  Cowork desktop sessions skip a symlinked `~/.claude/CLAUDE.md`; cloud sessions
  never read `~/.claude`.
- Write-through hazards to the shared source: Gemini's memory tool can edit the
  global `~/.gemini/GEMINI.md` (the link); Antigravity's built-in prompt appends
  rules to `~/.gemini/config/AGENTS.md`, so never link that file;
  `template/prompts.md` and `docs/prompts-advanced.md` redirect into
  `~/.claude/CLAUDE.md`.
- zkfy: `skills/vault-query/` and `scripts/knowledge-launcher.py`, the targets
  of the live links, are untracked in the zkfy checkout (7 tracked files are
  also modified). A fresh clone breaks the vault step the shared instructions
  require.
- Settings drift: the healthcheck's only failure is Codex `model` and
  `model_reasoning_effort` (live `gpt-6.1-sol`/`medium`, managed
  `gpt-6-astra`/`high`), set through Codex's model picker.
- Personal plugin repos in `../../plugin/` (dev-create, dev-guide, dev-security,
  dev-utilis, lang-packs, prompt-dev, zkfy) hold 222 skills, agents and
  commands, mostly from March 2026. None is installed except zkfy, and
  `prompt-dev` duplicates `dev-create`. Mapped to the spine, nothing covers goal,
  treehouse or PR.
- The shared `tools/instructions/AGENTS.md` gained a subagent line on 2026-10-16
  (live through the links, uncommitted in the original checkout).

### Decisions (round 2)

| ID | State | Decision / rationale |
|---|---|---|
| Q17 | Decided (user replied "keep on" to the recommendations) | Conflicts with the other AI's plan (`plan/project-redesign`, uncommitted in `../ai-cli-workspace-planning`, its Q1–Q18 dated 2026-10-12) resolve in this plan's favor: (1) personal-first; others get only the skills plugin, and a toolkit for others is a later stage; (2) Gemini CLI is dropped, and `~/.gemini/GEMINI.md` stays linked for Antigravity; (3) personal values stay in the repo (`tools/settings/managed.json`); (4) a weekly CI job opens a PR. Its other items (four workflows, `~/.config/agent-toolkit/`, local review bundles, the Agent Toolkit name) are not adopted; its workflow list is input to the skill-set question. |
| Q18 | Decided (user) | The global `AGENTS.md` is empty. The user narrowed the rules question to the global file, reviewed a 53-line "map" draft (admission rule: a line stays only if it applies to every project in every CLI), and answered "If that is the case, leave it empty" and "erase all of the content". The links from each CLI stay, so anything added later reaches every CLI at once. Implementation consequences: `scripts/install-global-instructions.py:65-66` refuses an empty source and `tests/test_global_instructions.py:169-171` asserts that, so the installer must accept an intentionally empty file (keep the missing-file and 32 KiB checks); vault retrieval then depends on the `vault-query` skill's own description (Claude and Pi load it today; Codex and Antigravity once skills are linked); docs that call the retrieval section resident (`docs/pi/CAPABILITIES.md`, the `install-vault-knowledge.py` docstring) need updating. Applied to the original checkout on 2026-10-16 at the user's request ("1 now"), uncommitted: the live source is empty (backup: `~/.local/state/ai-cli-workspace/global-instructions/manual-backup-20261016-144506/AGENTS.md`, which holds the previous 60 lines including the user's subagent line), the installer accepts an empty source (missing-file and 32 KiB checks kept), and a new test covers it (39 tests pass). The healthcheck is unchanged: only the Codex model drift fails. |
| Q19 | Decided (user) | The starting skill set is `grilling` and `vault-query` (renamed `query`, Q20) only. This revises Q13: `grill-me` (upstream it only calls `grilling`) and `skill-creator` (no uses in 60 days) leave the bundle; Claude keeps its claude.ai-synced copies (A6). Usage evidence: `grill-me` was the only skill used in all three CLIs, `vault-query` was read in Codex and Pi. |
| Q20 | Decided (user); done 2026-10-16, uncommitted | Rename `vault-query` to `query`, refactored at the skill's source location (zkfy `skills/query/`, `name: query`), not by renaming links. Done: folder moved (it is untracked in zkfy); `scripts/install-vault-knowledge.py`, `scripts/install.sh` and `tests/test_knowledge_adapter.py` updated (39 tests pass); live links migrated to `~/.claude/skills/query` and `~/.pi/agent/skills/query` (old links removed, receipt updated, a re-run shows 0 changes); prose references updated in both repos, while ADRs keep the historical name. No collision: no built-in `/query` in Claude, Codex or Antigravity, and no other skill named `query`. |
| Q21 | Decided (user); done 2026-10-16 | The `query` skill and its engine stay owned by zkfy and are committed there, which removes the fresh-clone blocker. zkfy commit `f4caaf2` adds only the 7 previously untracked files (`skills/query/SKILL.md`, `scripts/knowledge.py`, `scripts/knowledge-launcher.py`, `scripts/knowledge-hook.py`, `scripts/requirements-knowledge.txt` (PyYAML), `tests/test_knowledge.py` (25 tests pass), ADR-0003); the user's 7 modified zkfy files stay uncommitted. Not pushed (the user's call). Later fix: once the zkfy plugin is reinstalled from a commit that contains `skills/query`, Claude would list both `query` and `zkfy:query`. |
| Q22 | Decided (user); done for `query` 2026-10-16 | Skills reach every CLI by symlinks from one source, not by per-CLI plugins: `~/.claude/skills/<name>` for Claude (it does not read `~/.agents`) and `~/.agents/skills/<name>` for Codex and Pi (both read it; Pi's own `skills/` link is dropped to avoid a duplicate-name warning). Antigravity follows once its skills path is verified. This replaces installing this repo's plugin on the owner's machines (Q1a/A2); a plugin manifest remains a later item for sharing with others. Done for `query`: `scripts/install-vault-knowledge.py --target claude|agents|both`, `install.sh` maps codex and pi to `agents`, the Pi-only link was removed, and `codex debug prompt-input` (no model call) lists the skill from `~/.agents/skills` (Codex labels it `zkfy:query` because its real folder is inside the zkfy plugin). `grilling` is not imported yet. |
| Q23a | Decided (user) | Memory was split by the user into three topics: task memory (handing a half-finished task to the next session or CLI), project memory (per-project files to read, aliases such as "gdocs" for a specific Google Doc) and engineering docs (coding rules, language and framework docs, principles such as SOLID). Task memory exists only for repo work: a task file in that repo at `docs/plans/<task>.md`, committed. Sessions not tied to a repo get no handoff memory. Evidence: in the last 90 days every repo worked in was the user's own (no team repos), about 40% of sessions ran outside any repo (mostly `~`), and the same folders were used from several CLIs. |
| Q23b | Decided (user); done 2026-10-16 | The user pointed out that the empty global file was why nothing tells a CLI where task state lives, and chose to fix it there, revising Q18: the global `AGENTS.md` holds only rules that apply in every repository and every CLI, and the task-memory rule is the first. Approved text ("y"): in a git repository, a task that spans sessions is recorded in `docs/plans/<task>.md` (or wherever the repository's own instructions say) with status (`active`/`done`), goal, decisions, done and changed files, checks run and next step; read any active task file at session start and update it before stopping or switching tools; outside a repository keep none. No commit rule, so repositories that forbid AI commits (the CS vault) are respected. Live through all four links; commit `12904ff` on the feature branch. Also, with the user's approval, the vault's own `AGENTS.md` now names the `query` skill (the file is untracked in the vault's git; not committed, per the vault's rules). |
| Q23c | Decided (user); verified 2026-10-16 | Project memory (files every session must read, aliases such as "gdocs" for a specific Google Doc) lives in an `AGENTS.md` at the project root; the user's condition was that every target CLI reads it. Runtime checks with a throwaway project: Codex includes it in its prompt (`codex debug prompt-input`, no model call), Pi and Claude Code (Haiku) both answered a probe word stated only in that file; Claude did so for a project under `~`, where only the user-level `~/.claude/CLAUDE.md` sits above (that file does not switch native `AGENTS.md` reading off). Antigravity reads `AGENTS.md` per its docs, not checked at runtime (never logged in). Rule: when a repo also has a `CLAUDE.md` (or `.claude/CLAUDE.md`), Claude reads that instead, so it must link to `AGENTS.md` (this repo) or import `@AGENTS.md` (the CS vault does). zkfy breaks the rule today: a separate `CLAUDE.md` and no `AGENTS.md`, so Codex and Antigravity read nothing there. Claude's "remember" still writes to its private auto memory unless told to write to `AGENTS.md`. |
| Q23d | Deferred (user) | Engineering docs (coding rules, language and framework docs, principles such as SOLID) were an illustration, not a requirement for this stage. Nothing is built for them now; the shared MCP list (context7, unused in 60 days) stays unchanged until revisited. |
| Q24 | Decided (user); not implemented yet | Managed settings split in two. Safety keys (Codex `approval_policy` and `sandbox_mode`, Claude's two skip-permission-prompt flags) are put back on every install, and a difference fails the healthcheck. Preference keys (model, effort, advisor model) are written only when the CLI has no value yet, so a new Mac starts with them and later picks from each CLI's own model menu stay; the healthcheck reports a difference as information. Evidence: the healthcheck's only failure was Codex `model`/`model_reasoning_effort` changed through Codex's picker; `/model` ran 19 times in Claude in 60 days. The Gemini block is removed per Q17. |
| Q25 | Decided (user); not implemented yet | The weekly docs-update PR (Q17) also flags changes that touch this setup: a deterministic script searches the week's doc diff for what the repo relies on (managed setting names, `AGENTS.md`, `~/.agents/skills`, skills, MCP) and lists hits at the top of the PR. No AI summary and no API key in CI. Already settled for the same job: repair Codex discovery (the index moved to `learn.chatgpt.com/docs/llms.txt`), add Pi (`docs.json`) and Antigravity's missing harness pages, drop Gemini, and refuse to replace a mirror that shrinks sharply (page-count floors for every source). |

Usage evidence for later questions (Claude Code, last 60 days, 64 sessions): the
only skill used across several projects is `grill-me` (6 uses, 4 projects);
`/model` ran 19 times; context7 had zero calls (the only MCP server used was
claude.ai's Claude Docs connector, 29 calls); sessions concentrate in this repo
(21), the Obsidian CS vault (21) and the home folder (14).

Usage in Codex and Pi (last 60 days): about one session a week each; `grill-me` read 3 times in Codex and 2 in Pi; `vault-query` read 3 times in Codex (all prompted by the global instructions) and 5 in Pi; context7 never invoked in Codex.

Implementation so far (2026-10-16): branch `feat/empty-global-instructions-query-skill` in the original checkout holds commits `00859ae` (Q18), `164297d` (Q20), `663ab84` (Q22) and `12904ff` (Q23b); zkfy holds `f4caaf2` (Q21). Nothing is pushed.

Current question: Q26, Antigravity in this round.

## Layout

```text
ai-dotfiles/
├── README.md        for humans: what it is, how it works, how to change things
├── AGENTS.md        for AI: map and rules (CLAUDE.md is a symlink to it)
├── tools/           you edit; installed into each tool (unchanged paths inside)
│   ├── instructions/AGENTS.md   shared global instructions
│   ├── settings/managed.json    keys that must match on every Mac
│   └── mcp/servers.json         shared MCP servers
├── skills/          the ai-dotfiles plugin (skills only) plus skills.lock (source, commit, license)
├── upstream/        machine-written, never edit: official docs per tool
├── scripts/         install, check, update, plus the Python helpers they call
├── tests/
└── docs/            how-it-works.md, adr/, plans/, archive/
(also: plugin manifests at the root, e.g. .claude-plugin/, as zkfy does; .github/workflows/)
```

Rules: you edit `tools/` and `skills/`; scripts apply them; only the update job
writes `upstream/`. Because `tools/` keeps its current inner paths (the user's
reason was "fewer files move"), the instruction links change only by the repo
folder's rename. Each tool's plugin format (Codex, Pi, Antigravity CLI and IDE)
still needs checking against current docs; Claude's root-as-plugin layout is
already proven by zkfy.

What each tool supports natively (checked 2026-10-08 against mirrored docs and
Pi 1.0.2's installed README; not checked at runtime):

| | Skills | Agents | Hooks | Rules |
|---|---|---|---|---|
| Claude | yes (commands merged into skills) | yes, in plugins | yes, in plugins | `~/.claude/rules/`, not in plugins |
| Codex | yes | native, but plugins hold only skills and MCP | native, but not in plugins | means command-approval rules, a different concept |
| Pi | yes | no ("skips features like sub-agents") | via TypeScript extensions | no |
| Antigravity CLI | yes | yes, in plugins | yes, in plugins | yes, in plugins |

## Cleanup list

Approved by the user (Q12), with one change: delete the research docs instead of
archiving them.

| Action | Files | Why |
|---|---|---|
| Delete | `template/` (4 files) | `prompts.md` would overwrite the shared instructions through the link. The other three describe the retired Claude-only workspace. |
| Delete | Repo-root `GEMINI.md` link | Gemini CLI is dropped. Antigravity reads both `GEMINI.md` and `AGENTS.md` in a folder, so keeping both may load the same text twice. `~/.gemini/GEMINI.md` (global) stays. |
| Delete | `docs/gemini/` (95 files) | Mirror and catalog for the dropped Gemini CLI; it can be regenerated from git history. |
| Delete | 12 research docs at `docs/` top level, plus their index `docs/INDEX.md` | Claude-specific Traditional Chinese research from April to July; nothing current depends on it. Git history keeps them. |
| Archive | `CHANGELOG.md` | Stopped on 2026-06-07; git history and ADRs replace it. |
| Archive | `docs/codex/CAPABILITIES.md` | Superseded parity catalog. |
| Merge, then remove | `CONTEXT.md`, `tools/README.md`, `docs/global-instructions.md`, `docs/pi/CAPABILITIES.md` | Q10: their content moves into README, AGENTS and how-it-works. |
| Keep | ADRs 0001–0005, existing `docs/archive/`, `.serena/`, CI config, repo-root `CLAUDE.md` link | A new ADR-0006 will record this redesign. |

## Conflicts with the other AI's plan

Read-only comparison on 2026-10-08 with branch `plan/project-redesign`
(worktree `../ai-cli-workspace-planning`, its step "Q13, project name"):

| Topic | This plan | Other plan | Status |
|---|---|---|---|
| "For others" | Only the skills are shared, as a plugin; config stays personal; repo private for now (Q1a, Q5) | A reusable toolkit that other developers run with their own configuration, without editing its code (its Q1, Q2); also portable plans and handoffs (its Q3) | Resolved (Q14): this plan now, the toolkit later |
| Gemini CLI | Dropped (Q2) | Tested support in the first release (its Q4) | Resolved (Q15): dropped |
| Antigravity CLI and IDE | Both (Q2a) | Both (its Q6) | Same |
| ECC and skills intake | Copy, pin, diff-review (Q4, Q7) | Adopt selected items, track revisions and adaptations, review diffs (its Q8, Q9) | Compatible |
| Name | `ai-dotfiles` (Q8) | Pending | Open there |

## Execution plan (not started; a later task per Q16)

Phase 0, prerequisites
1. Retire the other AI's diverging plan copy in favor of this one (Q14 and Q15
   resolved the conflicts). Only one migration may touch the live instruction
   links.
2. Merge `origin/main` into the working branch; never check out `main` in the
   live checkout. Resolve the 112 mirror conflicts by taking `main`'s side or by
   re-running the sync.

Phase 1, targets (Q2, Q2a, Q15)
3. Drop Gemini CLI as an installer target: its blocks in `managed.json` and
   `servers.json`, the target lists in the scripts and healthcheck, and the
   tests. Keep the `~/.gemini/GEMINI.md` link, relabeled as Antigravity's.
4. Add the Antigravity CLI (settings, MCP, plugin) and the IDE once research
   items R-a and R-b confirm their surfaces. Use native commands where they exist
   (ADR-0005's rule); never hand-edit a file a CLI manages if a command exists.
5. Update the shared global instructions, `tools/instructions/AGENTS.md`. Line 3
   lists "Claude Code, Gemini CLI, Codex CLI, and Pi"; line 35 names Gemini;
   lines 48–50 route the vault-query procedure ("Pi uses …; other CLIs use
   `~/.claude/skills/…`"), which must also be right for Antigravity. Every CLI
   loads this file, so the edit goes live as soon as the live checkout has it.
   The repo name on line 4 changes in Phase 6.

Phase 2, structure (Q6, Q9, Q12)
6. Move the mirrors to `upstream/docs/<tool>/` (claude, codex,
   antigravity-cli), add pi and antigravity-ide, and delete `docs/gemini/`.
7. Apply the cleanup list and fix the broken crawler-research link. Also make
   `install.sh` dry-run by default (agent default A1 below; it changes the
   behavior the README documents).

Phase 3, skills plugin (Q1, Q1a, Q4, Q5, Q8a, Q9a, Q13)
8. Create `skills/` with `grill-me` and `grilling` (both locally edited, see
   Q13) and `skill-creator`, each with its LICENSE file, plus
   `skills/skills.lock` recording source, path, commit, license and whether
   there are local edits.
9. Add plugin manifests: Claude's `.claude-plugin/` at the repo root (A2), plus
   Antigravity and Codex once R-a confirms their formats (Codex plugins hold
   skills and MCP). Pi has no confirmed plugin system, so the installer links
   each skill into `~/.pi/agent/skills/` (A3).
10. The license check in tooling refuses to copy anything that isn't MIT or
    Apache.

Phase 4, updates (Q3, Q3a, Q7)
11. One update entry point:
    - sync the docs for Claude, Codex, Pi, and the Antigravity CLI and IDE into
      `upstream/docs/` (A4);
    - report picked skills that changed upstream (as diffs) and new skills in
      ECC, `anthropics/skills` and `mattpocock/skills` (listed only).
12. The weekly workflow opens a PR instead of pushing to `main`; the same
    command runs locally.

Phase 5, docs (Q10, Q11)
13. Write `README.md`, `AGENTS.md` and `docs/how-it-works.md` in English.
14. Add ADR-0006 recording this redesign. It supersedes the parts of ADR-0005
    covering the Gemini CLI target, the Antigravity exclusion, ECC removal (now
    catalog intake) and `tools/skills/` (now the top-level `skills/`).

Phase 6, rename (Q8), done once and last
15. Rename the GitHub repo `jasonsie/ai-cli-workspace` to `ai-dotfiles` (an
    outward-facing step; confirm at the time). GitHub redirects the old URL.
    Update the remote.
16. Move the local checkout to `.../ai-dotfiles`, then immediately re-run the
    installer with `--replace-instructions`; until then the four links dangle.
    Also:
    - move `~/.local/state/ai-cli-workspace/` to `~/.local/state/ai-dotfiles/`;
    - update the repo name in `tools/instructions/AGENTS.md`, the sync user
      agent, `.serena` `project_name` and the doc titles;
    - copy Claude's path-keyed project memory folder to the new key.
17. Verify:
    - the healthcheck is green and `install --dry-run` shows 0 changes;
    - each tool loads the instructions in a fresh session;
    - the plugin installs in Claude and in every other tool that supports it.

Agent defaults (chosen without asking the user; confirm before implementing):
- A1: `install.sh` becomes dry-run by default, matching the repo's rules but
  changing what the README documents ("bash scripts/install.sh  # apply").
- A2: the repo root doubles as the Claude plugin root (zkfy's layout), rather
  than a nested `plugin/` folder.
- A3: Pi gets skills by direct links into `~/.pi/agent/skills/`, since no Pi
  plugin system is confirmed.
- A4: mirror folders are named `upstream/docs/<tool>/`, with the tool names
  `claude`, `codex`, `pi`, `antigravity-cli`, `antigravity-ide`.
- A5: dropping Gemini CLI leaves its existing files (settings, MCP entry) in
  place; the installers just stop managing them.
- A6: the claude.ai-synced copies of `grill-me` and `skill-creator` stay; Claude
  will list them next to the plugin's `ai-dotfiles:` versions.

Research items:
- R-a: plugin formats and install commands for Codex, the Antigravity CLI and
  IDE, and Pi packages.
- R-b: the Antigravity IDE's surfaces: global rules (does it read
  `~/.gemini/GEMINI.md`?), MCP and skills.
- R-c: doc sources for Pi and the Antigravity IDE.
- R-d: which Antigravity settings keys to manage.

Later stages, not in this plan: a toolkit others run with their own configuration
(Q14), making the repo public (Q5), local models (Q2), and possibly Gemini CLI
again (Q15).

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
- That note's `#Mental Model` and `#Spine As Package` describe an `ai-to-go`
  bundle in three groups: `memory` (docs-builder), `dev` (grilling, goal,
  treehouse) and `pipe` (testing, PR, review, lint). This was design intent
  recorded on 2026-08-26, before ADR-0005. This plan adopts its direction (a
  portable skills bundle) but not its three-way split (Q8a).
- That note's `#Doc Freshness` and `#Appendix` leave the doc-refresh trigger
  open: scheduled CI (unreviewed automation) or an on-demand local run (reliable
  but forgettable). Q7 resolves it with a scheduled job that opens a PR for review.

These applications are synthesis, not additional user requirements.

## Handoff

- Completed: the requirements interview (Q1–Q16) with the user, a read-only
  comparison with the other AI's plan, and the execution plan. Sources: git,
  `gh` (runs, repo metadata, licenses), code reading, the mirrored docs,
  session-file timestamps, and the vault sections above.
- Changes, committed on `claude/project-redesign` (not pushed): this document,
  plus discovery links in `AGENTS.md`, `README.md` and `docs/INDEX.md` (copied
  verbatim from the other AI's version so the branches merge cleanly).
- Not done: no installer, doc sync, healthcheck or runtime test was run. No file
  outside this worktree was changed, except that edits made briefly in the
  original checkout before the branch split were reverted there.
- Existing user work: `.serena/project.yml` in the original checkout was already
  modified; it is untouched.
- Next (a later session, any AI): retire the other AI's plan copy, confirm
  A1–A6, do research items R-a to R-d, then follow the execution plan from
  Phase 0. Ask the user before pushing, before the GitHub rename, and before
  moving the live checkout.
