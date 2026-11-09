# How it works

This repository is the single source of the owner's global AI CLI setup. You edit
sources here; scripts apply them to each CLI's native folders; a healthcheck reads the
live state back. Earlier decision records (ADRs and finished plans) are in git history:
`git show 3507344:docs/adr/`.

## Layout

```text
config/              the sources the installers apply
  ai-clis.json         which CLIs are on, and where each one reads things
  global-agents.md     the rules every CLI loads in every project
  cli-settings.json    per-CLI `enforce` and `default` settings keys
  mcp-servers.json     MCP servers shared by the CLIs
  plugins.json         the plugin list: each plugin's GitHub source, pin and target CLIs
  upstream-docs.json   the documentation sources mirrored into docs/upstream/
skills/              shared skills; skills.lock pins adapted ones; daily-log/ holds the
                     daily-log command and the day pass; worktree-guard/ and small-commits/
                     their hooks; git/ a bundle: the git step skills and approve
scripts/             ai-dotfiles, install.sh, uninstall.sh, healthcheck.sh (entry points);
                     agent_hooks.py and agent_sessions.py (the CLIs' hook formats and
                     session stores behind one interface); agent_hooks.ts (Pi's extension);
                     statusline.py (the status line Claude Code and Antigravity run)
  install/             installer.py (shared by every step) and one file per step
  upstream/            the weekly docs sync and its pull request report
  tests/               unit tests for all of the above
docs/
  how-it-works.md      this file
  onboarding.md        this repo's report from /onboard
  agents/              the engineering skills' setup: issue tracker, triage labels, domain docs
  upstream/            machine-written mirrors of upstream docs, their indexes, and the skill catalogs
```

## The flow

```text
YOU EDIT                          APPLIED BY scripts/install/ (ai-dotfiles = install.sh)   LANDS IN
config/ai-clis.json           ─►  every step: which CLIs, and their paths  ─►  (the CLIs switched on)
config/global-agents.md       ─►  instructions.py (symlinks)               ─►  each CLI's global instruction file
config/cli-settings.json      ─►  settings.py (merges listed keys)         ─►  settings.json / config.toml
scripts/statusline.py         ─►  settings.py (the statusLine keys run it) ─►  Claude Code's and Antigravity's status line
config/mcp-servers.json       ─►  mcp.py (native `mcp add`, or a merge)    ─►  Claude Code, Codex, Pi, Antigravity
config/plugins.json           ─►  plugins.py (each CLI's plugin manager)   ─►  each CLI's plugin store; ~/.local/bin/<command>
skills/<name>/                ─►  skills.py (links)                        ─►  every CLI's skill folder
scripts/ai-dotfiles           ─►  skills.py (link)                         ─►  ~/.local/bin
skills/daily-log/scripts/     ─►  skills.py (link); launchd.py (plist)     ─►  ~/.local/bin/daily-log; ~/Library/LaunchAgents (04:00)
skills/worktree-guard/scripts/ ─► hooks.py (merge)                         ─►  each CLI's hook file
skills/small-commits/scripts/ ─►  hooks.py (merge)                         ─►  each CLI's hook file
scripts/agent_hooks.ts        ─►  skills.py (link)                         ─►  Pi's extension folder
                                  installer.py: reads ai-clis.json; the safe writes every step shares
                                  scripts/healthcheck.sh checks the live state

WEEKLY  config/upstream-docs.json ─► scripts/upstream/sync-upstream.py ─► docs/upstream/ on branch upstream-sync ─► review PR
```

`install.sh` writes by default; `--dry-run` previews; `--target=<cli>` limits a run to one
CLI listed in `config/ai-clis.json`. Each step is idempotent: a second run reports 0
changes. `ai-dotfiles` (linked on the first run) wraps the entry points from any folder:
`install`, `update` (fast-forward pull of `main` on a clean tree, then install),
`uninstall`, `check`.

## Which CLIs: config/ai-clis.json

Each entry names a CLI, switches it `on` or off, and says where it reads its global
instructions, settings, MCP servers, skills and, where it has them, hooks (`hooks`) or
extensions (`extensions`, Pi). Paths start with `~/`. The file is checked strictly: a
missing or unknown key, an `on` that is not `true` or `false`, or a CLI the steps have no
code for stops the run.

- **The file is the desired state.** A run installs for each CLI switched on and takes out
  of each CLI switched off what this repo put there: the instruction link (the original
  comes back), skill links, hook entries and Pi's extension. Settings keys and MCP servers
  stay, as with any uninstall.
  A CLI switched off gets no folders created.
- **A shared folder stays while any CLI that is on reads it** (`~/.agents/skills`, for
  Codex and Pi).
- **`--target` only narrows a run** to one CLI; `all` means every CLI in the file, on or
  off. `uninstall` removes for every selected CLI whatever its switch.
- **How each CLI's files are edited stays in code:** Codex settings are TOML, each CLI
  has its own `mcp add`, hook events differ, and Pi takes an extension.

`uninstall.sh` runs each step's `--uninstall` in reverse order and removes whatever points
into this repo: instruction links (restoring the file from before the first install),
skill links, hook entries, Pi's extension, the command links, and a settings key whose value
runs this repo's command (the status line). The other settings keys and the MCP servers stay
and are listed, because they hold no repo paths and could be the user's own. After it,
deleting the repo breaks nothing.

## Where each CLI reads things

| | Claude Code | Codex CLI | Pi | Antigravity (CLI and IDE) |
|---|---|---|---|---|
| Global instructions | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `~/.pi/agent/AGENTS.md` | `~/.gemini/GEMINI.md` |
| Project instructions | `CLAUDE.md`; `AGENTS.md` when no `CLAUDE.md` exists | `AGENTS.md` | `AGENTS.md`, else `CLAUDE.md` | `AGENTS.md`, `GEMINI.md` |
| User skills | `~/.claude/skills` | `~/.agents/skills` | `~/.agents/skills`, `~/.pi/agent/skills` | `~/.gemini/config/skills` |
| Settings file | `~/.claude/settings.json` | `~/.codex/config.toml` | `~/.pi/agent/settings.json` | `~/.gemini/antigravity-cli/settings.json` |
| MCP servers | `~/.claude.json` via `claude mcp add` | `config.toml` via `codex mcp add` | `~/.pi/agent/mcp.json` via `pi mcp add` | `~/.gemini/config/mcp_config.json`, merged (no `mcp add`) |
| Hooks | `~/.claude/settings.json` (`hooks`) | `~/.codex/hooks.json`, run after approval in `/hooks` | none; `~/.pi/agent/extensions/*.ts` | `~/.gemini/config/hooks.json` |
| Status line | `statusLine` in `settings.json` runs `ai-dotfiles statusline` | `tui.status_line` in `config.toml`: Codex's own items | built-in footer; only an extension could replace it | `statusLine` in `settings.json` runs the same script |
| MCP server guidance | server instructions | server instructions | only the `description` in `mcp-servers.json` | not documented |
| Explicit-only skill | `disable-model-invocation: true` | `agents/openai.yaml`: `policy.allow_implicit_invocation: false` | `disable-model-invocation: true` | none documented; may load implicitly |

The installers read the paths in the first six rows from `config/ai-clis.json`. To move
a CLI's folder, edit its paths there; `CLAUDE_CONFIG_DIR`, `CODEX_HOME` and
`PI_CODING_AGENT_DIR` are never read for paths, and a run warns when one is set and
disagrees with the file.

Checked at runtime on 2026-10-16 and 2026-10-17: every CLI loads the global file and a
project `AGENTS.md`, and lists the `grilling` skill. Codex can be checked
without a model call: `codex debug prompt-input "hi"` prints what it would send.

## Plugins: config/plugins.json

A plugin is an installable bundle (skills, commands, agents, hooks, MCP servers, commands
for PATH) kept in its own GitHub repo. `config/plugins.json` lists the ones every Mac gets,
the way `package.json` lists dependencies; npm's `install` and `uninstall` are the model,
nothing more. Each entry names a plugin (its key is the manifest's `name`), its GitHub
`source` (a repo whose root is the plugin), an exact `version` (the pin) and the `targets`
it goes to. The plugins step installs the pin's release tag, `<name>--v<version>`, through
each CLI's own plugin manager, and reads the CLI back afterwards: a CLI can report success
and keep the old version.

| | Claude Code | Codex CLI | Pi | Antigravity |
|---|---|---|---|---|
| Install | `plugin marketplace add <repo>#<tag>`, then `plugin install` | `plugin marketplace add <repo> --ref <tag>`, then `plugin add` | `pi install git:github.com/<repo>@<tag>` | `agy plugin install <repo URL>/tree/<tag>` |
| Move to a new pin | set the ref in `extraKnownMarketplaces`, `marketplace add` again, `plugin update` | set `ref` under `[marketplaces.<name>]`, `plugin marketplace upgrade` | `pi install` at the new tag | `agy plugin install` at the new tag |
| Remove | `plugin uninstall`; the marketplace too when nothing else uses it | `plugin remove` | `pi remove` | `agy plugin uninstall` |
| Read back | `plugin list --json` | `plugin list --json` | `settings.json` (`packages`) | `plugin list --json` |
| Plugin `bin/` on PATH | yes, after the user's own entries | no | no | no |

Rules the step follows:

- **Before any change:** every tag it needs exists on GitHub (a missing one stops the run
  and prints `claude plugin tag --push`), and each plugin's manifest at its tag agrees with
  the list: named as its key, every dependency it declares listed, aimed at the same CLIs,
  pinned inside its range (`^`, `~`, exact, `>=`). Dependencies are listed with their own
  pin, like strict peer dependencies; nothing is resolved.
- **Only ai-dotfiles moves versions.** Claude's managed marketplaces get `autoUpdate: false`;
  Claude's own auto-update would otherwise move a dependency past its pin.
- **Commands on PATH, like an npm global install.** For a plugin whose `bin/` holds
  executables, one checkout at the tag lives in `~/.local/share/ai-dotfiles/plugins/<name>`
  and each command is linked into `~/.local/bin`, so it runs the same in every CLI and the
  shell. A name there that is not absent or our link stops the run. An unchanged pin is
  checked offline (`git describe` in the checkout).
- **The list controls only what it names.** Dropping a plugin, or a CLI from its targets,
  removes it there on the next install, only where the receipt says the step installed it.
  A plugin a CLI already had when first listed is taken over: moved to its pin, recorded as
  such, never removed. A CLI switched off, and `ai-dotfiles uninstall`, leave plugins, links
  and checkouts in place and list them, like MCP servers.
- **A plugin the user disabled stays disabled;** the step never runs a command that would
  re-enable it.
- **Gaps are the plugin's job.** ai-dotfiles distributes; it never adapts content. A feature a
  CLI cannot load as shipped is filled with that CLI's own feature where one exists (commands
  as skills, Antigravity's own `hooks.json` and `mcp_config.json`, a Pi extension for hooks
  and MCP), else documented. The rules, with the facts behind them and the trial-install
  commands, are the `portable-plugin` skill. web-clipper 2.2.1 and zkfy 1.8.0 go to all four CLIs.

Adding, bumping or removing a plugin is a hand edit of `config/plugins.json`, applied by
`ai-dotfiles install`; a release in a plugin repo ends by bumping its pin here. `ai-dotfiles
check` needs nothing plugin-specific: the step is idempotent, so a missing plugin, a wrong
version or a plugin to remove shows up as a pending change.

## Principles

- **Shared behavior, native differences.** The same intent reaches each CLI through its
  native surface. A missing capability is documented, never shimmed.
- **Link what is read-only; merge what a CLI writes.** Instruction files and skills are
  symlinks to one source. Settings files are never linked, because each CLI writes its
  own state into them; only listed keys are merged.
- **Global only what applies everywhere.** The global agents file
  (`config/global-agents.md`) is loaded into every session of every project, so it holds
  only rules true in every repository and every CLI. Everything else lives in a project's
  `AGENTS.md` or in a skill, which loads on demand.
- **Never write through a link.** A CLI's memory or rule-saving feature must not edit the
  shared file; `~/.gemini/config/AGENTS.md`, where Antigravity appends rules, is never linked.
  The one deliberate exception is the `house-style` skill, which writes its `STYLE.md` and
  `templates/` in this repo on a branch: live in every CLI at once through the links; the
  merge keeps them.
- **Portable across Macs.** No usernames, checkout paths, or Homebrew prefixes in `config/`
  or `scripts/`; scripts resolve their own location. The healthcheck enforces this.
- **Safe by default.** `--dry-run` previews, idempotent, back up before writing,
  refuse to overwrite anything a script did not create, and roll back on failure. Every
  step writes through `apply()` in `scripts/install/installer.py`, so these rules live in
  one place.

## Settings: enforce and default

`config/cli-settings.json` (version 2) lists, per CLI, an `enforce` group and a `default`
group. `enforce` holds the settings this repo owns (approval policy, sandbox, permission
prompts, the status line) and is put back on every install. `default` holds model choices
and is written only while a CLI has no value; a model you pick in a CLI's own menu stays,
and the preview and healthcheck report it as a "local choice kept". A key is a dotted path;
for Codex's TOML, a top-level key or `table.key`.

## Memory

- **Across sessions:** the `handoff` skill writes the session's state to a temporary file
  that another session or CLI picks up; nothing in a repository tracks tasks.
- **Project memory:** the project's `AGENTS.md`, read natively by every CLI. When a
  project also has a `CLAUDE.md`, it links to `AGENTS.md` or imports it with `@AGENTS.md`.
- **Claude's auto memory** stays on as a per-machine, Claude-only scratchpad.

## Daily log

The daily logger (`~/Documents/Claude/Projects/daily-logger/<yyyy>/<Mon>/week-N`) is the
one journal: hand-written entries, the learning-tutor's study block, and one work entry per
project per day (`- [X] <project>: <what the day was about>`, `keyword:`, `description:`).
The `daily-log` skill owns its grammar (`skills/daily-log/LOG-FORMAT.md`) and the one writer,
`daily-log` (`skills/daily-log/scripts/daily_log.py`, linked into `~/.local/bin`; it imports
nothing from the repo, so a copy is a complete writer). The engine in
`~/Documents/Claude/Projects/learning-tutor` writes its day block through it (its
`vendor/daily_log.py` is a byte-identical copy, the last resort for Cowork's sandboxed runs,
refreshed by `scripts/vendor_daily_log.py` and checked by a test), and every
`<key>-tutor-daily` Cowork task is `TUTOR-DAILY.md` rendered for one key (`daily-log tutor-daily`).

```text
04:00  launchd ─► daily-log day --write
       ─► the evidence: yesterday + 3 days back, 04:00 to 04:00; per day the existing block, the
          keywords in use, then per working folder its git facts and its sessions (Claude Code, Codex,
          Pi stores read by scripts/agent_sessions.py; temp folders dropped); no sessions, no run
       ─► piped into claude -p "/daily-log day" (sonnet; the Bash tool only, daily-log add only; 15 turns)
       ─► the model names the projects from the content and writes the uncovered ones:
          daily-log add --date D --done "<project>: ..." "keyword: ..." "description: ..."
```

- **One writer:** the pass. No session logs a turn or a unit of work on its own, and
  `daily-log add` refuses a work entry whose lines are not `keyword:` then `description:`,
  so a session that remembers an older shape cannot write it. "Log it" by hand still works.
- **Fill gaps only:** an entry the block already has, by hand or by machine, is never
  touched; `daily-log add` refuses a second label for the same project (`ai_dotfiles` and
  `ai-dotfiles` are one) and `--rewrite` replaces it on purpose (`daily-log day --rewrite`).
  A Mac asleep at 04:00 runs the job at its next wake, so it lands whenever the day starts;
  a day the Mac was off is caught up by the next run.
- **The evidence is piped, not fetched:** the model gets the day's evidence with its prompt
  and only writes. Letting it run `daily-log day` itself met the Bash tool's timeout on a
  cold cache, a background wait, and a fallback wakeup that ran the pass twice (2026-11-03).
- **Installed by `scripts/install/launchd.py`:** `~/Library/LaunchAgents/com.ai-dotfiles.daily-log-day.plist`,
  the PATH (`daily-log`, `claude`, python3, git) rendered at install; log in
  `~/Library/Logs/ai-dotfiles/`. The healthcheck checks the job is loaded. Before November
  2026 a Stop hook nudged every session that edited files; `hooks.py` takes its entries and
  state folder out when it finds them.

## Status line

One script, `scripts/statusline.py`, draws the status line in Claude Code and Antigravity: each
runs `ai-dotfiles statusline` (the `statusLine` key `cli-settings.json` enforces) with the
session as JSON on stdin and shows what it prints.

```text
📁 ~/repo  🌿 main ⎇ agent-2  🤖 Fable 5.1 · max · ⚡fast  📟 v2.1.318
🧠 Context: 93% [=========-]
⏳ 5h 23% → 14:00  7d 41% → Thu 08:00  💰 $0.12
```

- **Line 1:** the folder; the branch, with the worktree's name when the session works in a
  linked one; the model with its effort, `thinking off` and `⚡fast` only when so; the CLI's
  version. While a session has a worktree of worktree-guard's the work name
  (`🌿 fix/prune-worktrees`) replaces the branch: Claude Code reads it from the record beside
  the worktree its folder is in, Antigravity (its folder stays the main checkout) from the
  guard's record of the session, found by the payload's `session_id`. Once the worktree is
  gone the branch shows again.
- **Line 2:** the context left, from the CLI's own percentage, `?` before the first reply.
  **Line 3:** the rate-limit windows (Claude: 5h, 7d, spend; Antigravity: its quota buckets) and
  the cost, each when the CLI sends it; no line when it sends neither. A window shows the share
  used and the local time it resets, with the weekday when that is not today; a window whose
  reset has passed is left out. The figures are those of the session's last API response: the
  CLI re-runs the script on changes in the session and at each reset time, not on a clock, so
  they can lag what other sessions have spent since.
- **Codex** runs no script: `tui.status_line` lists its own items (`current-dir`, `git-branch`,
  `model-with-reasoning`, `codex-version`, `context-remaining`) and cannot follow a steered
  session, so its footer keeps showing the main checkout: **a gap, not emulated**. Instead
  worktree-guard answers the session's next tool call after a worktree is made or deleted with
  a one-line notice (a `systemMessage`): `fix/x works in <path>`, then `fix/x is deleted; the
  session is back in <repo>`. The notice comes with the next call, not the moment the worktree
  changes, so a deletion by `ship` is told only if the session makes another call.
  **Pi**'s built-in footer already shows the folder, branch, model, thinking level, context and
  cost; the Pi extension (`scripts/agent_hooks.ts`) adds a footer status, `worktree`, with the
  work name, set and cleared by the same next-call answer. A resumed Pi session shows it after its
  worktree next changes.
- The script never fails: bad input prints what it can and exits 0. `ai-dotfiles check` runs
  it once. An uninstall removes the two `statusLine` keys, which would otherwise run a command
  that is gone.

## Small commits

A hook on every shell command gates `git commit` (PreToolUse on Bash / `run_command`; Pi
through `scripts/agent_hooks.ts`, which plays both hooked features). There is no rule text
in `config/global-agents.md`: the hook is the rule, and its block message points at the
`small-commits` skill, which holds the protocol an agent follows (measure, plan, split,
commit); `scripts/small_commits.py` in it is the hook.

- **What it measures:** added plus deleted lines of what the commit would hold: the staged
  diff; with `-a`, every tracked change; with paths, those paths; with `--amend`, the result
  against the parent.
- **Two tiers:** over 300 lines the first attempt is blocked with a split hint, and an
  identical retry in the same session passes. Over 600 it is blocked unless the command sets
  `ALLOW_LARGE_COMMIT="<reason>"` and the message carries a `Large-commit: <reason>` trailer;
  the override is the user's to grant.
- **The message:** a subject `type(scope): outcome` of at most 72 characters, and the
  trailers `Why:`, `Scope:`, `Verified:` (`Part: n/m` when the change is split).
- **Left out of the count:** binaries, lockfiles, and files `.gitattributes` marks
  `linguist-generated` or `-diff`; this repo marks `docs/upstream/**`. A commit that finishes a
  merge, cherry-pick, revert or rebase passes untouched.
- **Fails open:** a failure never blocks a commit; the hook says "not checked" and the agent
  reports it.
- **`ai-dotfiles commit check [git commit args]`:** prints what the hook would say, the size by
  file and the verdict, without committing.
- **Installed by `scripts/install/hooks.py`** as a second feature beside worktree-guard: one
  PreToolUse entry per CLI with the shell matcher (Antigravity: `ai-dotfiles-small-commits-pre`).
  State, the sizes a session was warned about, is in `~/.local/state/ai-dotfiles/small-commits/`.

## Approve

When the user has reviewed an agent's branch and says "approve", the `approve` skill lands
it. The agent commits (small-commits) and writes the PR body (pr skill); then
`ai-dotfiles approve --title T --body-file F` runs the git step skills in order.

```text
skills/git/                          a bundle; the installer links each skill by its own name
  scripts/git_run.py                 the runner every step shares; tests fake git and gh here
  push-branch/   ai-dotfiles git push      origin gets the branch
  open-pr/       ai-dotfiles git pr        the PR, opened or reused
  approve-pr/    ai-dotfiles git review    approval as the repo's reviewer (git reviewer: the cache)
  archive-tag/   ai-dotfiles git tag       archive/<name> at the tip; worktree-guard imports it too
  merge-pr/      ai-dotfiles git merge     a merge commit
  prune-branch/  ai-dotfiles git prune     base pulled; branch deleted locally and on origin
  approve/       ai-dotfiles approve       preflight, then the six above, in that order
```

- **Steps:** preflight (a branch other than the base, no tracked changes), then the six.
  Each is skipped when done, so a stopped run is rerun as is; nothing is undone on failure.
  Each step's skill holds the fix for its own stops.
- **By number:** `ai-dotfiles approve <n>` lands PR n from any session, with no local branch or
  worktree: reviewer approval, archive tag at the PR head, merge commit, remote branch deleted,
  then the main checkout fast-forwarded only when git can without touching uncommitted files
  (never a stash or reset; otherwise skipped, with the reason). Each step is skipped when done.
- **The reviewer:** GitHub refuses self-approval, so each repo names its own reviewer login,
  cached in `git config --local approve.reviewer`. None cached: exit 3, and the agent asks
  the user and reruns with `--reviewer LOGIN`. A login is cached only once it has a `gh auth`
  token, is not the PR's author, and can read the repo. The script never invites an account;
  `ai-dotfiles git reviewer [LOGIN | --unset]` shows, sets or clears it.
- **The record:** an annotated `archive/<branch without its first segment>` tag at the branch
  tip, pushed before the merge commit, in the one format `archive-tag` owns: the commits' date
  span, the PR title, "merged and deleted", and a `PR:` line. A name taken by another commit
  gets the date; a tag already at the tip is reused.
- **`--dry-run`** prints each change it would make; read-only commands still run.

## Upstream updates

- `scripts/upstream/sync-upstream.py` mirrors every source in `config/upstream-docs.json`
  into `docs/upstream/<source>/`: each CLI's official docs (claude, codex, pi, antigravity)
  and GitHub-hosted style and docs-writing guides (google, facebook), the latter at
  `<source>/<repo>/<path>`, HTML and reStructuredText converted by pandoc. Each source has a
  floor (a GitHub source: every listed file, and each glob its own); below it, the previous
  copy is kept and the run fails, so a moved index or a renamed file cannot wipe a mirror.
  Every source gets `MIRROR-INDEX.md` (pages, their `when` labels, the source's notes) and
  `MIRROR-INDEX.json` (titles, descriptions, heading outlines with line numbers, last
  commits); `docs/upstream/INDEX.md` lists the sources.
- Agents read the mirror through the `upstream-docs` skill: `find` a page, `outline` it,
  `show` one section. `collect-docs` adds a source: survey, config entry, sync.
- `scripts/upstream/report-upstream.py` writes the pull request description: pages changed
  per tool; changes that touch this setup (managed setting keys, instruction files, skill
  folders, MCP); picked skills that changed upstream since their pinned commit; and skills
  new in the watched collections (`docs/upstream/catalogs.json`).
- A skill adapted from another repository is pinned in `skills/skills.lock` (repository,
  path, commit, license, local edits; `path` may be a list of files). When the report
  shows it changed upstream, remove the local copy, add the upstream version, re-apply the
  local edits, and update the pinned commit and `which-skill`. A pinned file deleted
  upstream is reported as removed: follow a rename to the new name; with no successor,
  delete the local copy.

## Backups and rollback

| Step | Record | Rollback |
|---|---|---|
| Instructions | `~/.local/state/ai-dotfiles/global-instructions/backup-*/manifest.json` | `python3 scripts/install/instructions.py --uninstall` (restores the earliest backup) |
| Hooks | `~/.local/state/ai-dotfiles/settings/backup-*`; entries found by their command | `python3 scripts/install/hooks.py --uninstall` |
| Launchd (the daily-log pass) | `~/.local/state/ai-dotfiles/launchd/backup-*`; the plist found by its marker | `python3 scripts/install/launchd.py --uninstall` |
| Settings | `~/.local/state/ai-dotfiles/settings/backup-*` | Copy the backed-up file back |
| MCP (Antigravity's file) | `~/.local/state/ai-dotfiles/mcp/backup-*` | Copy the backed-up file back |
| Skills, commands, Pi extension | `~/.local/state/ai-dotfiles/skills.json` (links this repo created) | `python3 scripts/install/skills.py --uninstall` |
| Plugins | `~/.local/state/ai-dotfiles/plugins.json` (installed or taken over, per plugin and CLI; each `bin/` checkout's tag and commands); `settings/backup-*` for the edits to Claude's `settings.json` and Codex's `config.toml` | Empty the list and run `ai-dotfiles install`; `--uninstall` only lists what stays |
| Everything | the records above | `ai-dotfiles uninstall` |

## Glossary

- **Source:** a file under `config/` or `skills/` that an installer applies. Edit the
  source, never the destination.
- **Switch:** a CLI's `on` value in `ai-clis.json`; on means set up, off means taken out.
- **Managed key:** a settings key in `cli-settings.json`, either `enforce` or `default`;
  every other key belongs to the CLI or to you.
- **Local choice:** a `default` key whose live value differs from `cli-settings.json`; kept
  on purpose.
- **Mirror:** a machine-written copy of upstream docs under `docs/upstream/`; never edit it
  by hand. A **docs source** is one entry in `config/upstream-docs.json`, one folder there.
- **Floor:** the minimum number of pages a source must yield before its mirror is replaced.
- **Receipt:** a record of what a script created, so it never touches anything else.
- **Plugin:** an installable bundle (skills, commands, agents, hooks, MCP servers, commands
  for PATH) in its own GitHub repo; here, one listed in `config/plugins.json`.
- **Pin:** a plugin's exact version in `config/plugins.json`. Every CLI runs that version.
- **Release tag:** the git tag `<name>--v<version>` that marks a plugin release; a pin
  installs it.
- **Taken over:** a listed plugin that a CLI already had when first listed. Moved to the
  pin like any other, never removed.
- **Gap:** a plugin feature a CLI cannot load as shipped. Filled with the CLI's own feature
  where one exists, else documented; the plugin's job, not this repo's.
- **Emitted vs verified:** writing a config is not proof that it works. Verified means the
  CLI itself reports it (`mcp list`, a session listing the skill, `codex debug prompt-input`).
