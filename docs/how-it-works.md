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
  cloud.json           the skills cloud sessions leave out, each with the reason
  herdr-title.json     the label an agent's row in Herdr carries, and what decides it
skills/              shared skills; skills.lock pins adapted ones; daily-log/ holds the
                     daily-log command and the day pass; worktree-guard/, small-commits/ and
                     herdr-title/ their hooks, each declared in its feature.json; git/ a bundle:
                     the git step skills and approve
lib/                 features.py (each feature's feature.json, found by its folder) and door.py
                     (`ai-dotfiles hook`: one call per event runs every feature that wants it)
scripts/             ai-dotfiles, install.sh, uninstall.sh, healthcheck.sh (entry points);
                     agent_hooks.py and agent_sessions.py (the CLIs' hook formats and
                     session stores behind one interface); agent_hooks.ts (Pi's extension);
                     statusline.py (the status line Claude Code and Antigravity run);
                     cloud_session.py (what a cloud session on this repo gets at start)
  cloud/               environment.sh (a cloud environment's setup script) and setup.sh (what it runs)
  install/             installer.py (shared by every step) and one file per step
  upstream/            the weekly docs sync and its pull request report
  tests/               unit tests for all of the above
docs/
  how-it-works.md      this file
  agents/              the engineering skills' setup: issue tracker, triage labels, domain docs
  upstream/            machine-written mirrors of upstream docs, their indexes, and the skill catalogs
.claude/settings.json  the hooks a cloud session on this repo runs; see Cloud sessions
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
skills/*/feature.json         ─►  hooks.py (one door entry per event)      ─►  each CLI's hook file: ai-dotfiles hook
config/herdr-title.json       ─►  herdr_title.py (read on every call)      ─►  the label on the agent's row in Herdr
scripts/agent_hooks.ts        ─►  skills.py (link)                         ─►  Pi's extension folder; it calls the door
                                  installer.py: reads ai-clis.json; the safe writes every step shares
                                  scripts/healthcheck.sh checks the live state

WEEKLY  config/upstream-docs.json ─► scripts/upstream/sync-upstream.py ─► docs/upstream/ on branch upstream-sync ─► review PR
```

`install.sh` writes by default; `--dry-run` previews; `--target=<cli>` limits a run to one
CLI listed in `config/ai-clis.json`. Each step is idempotent: a second run reports 0
changes. `ai-dotfiles` (linked on the first run) wraps the entry points from any folder:
`install`, `update` (fast-forward pull of `main` on a clean tree, then install),
`uninstall`, `check`.

Run in a linked worktree (`.claude/worktrees/<name>`, which `ship-pr` deletes), the steps read
what they install from the worktree but name the main checkout in every link
(`installer.live_root()`); hook entries name no checkout, since each runs the door. So
`--dry-run` there previews what installing will change once the work merges, and the
healthcheck measures this Mac against the main checkout; its tests and portability check stay
the worktree's. Something the work adds, such as a new skill, is linked
before the main checkout has it, so install for real from the main checkout after the merge.

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
  commands, are the `portable-plugin` skill. web-clipper 2.2.1 and zkfy 1.8.1 go to all four CLIs.

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
⏳ 23% → 14:00  41% → Thu 08:00  💰 $0.12
```

- **Line 1:** the folder; the branch, with the worktree's name when the session works in a
  linked one; the model with its effort, `thinking off` and `⚡fast` only when so; the CLI's
  version. While a session has a worktree of worktree-guard's the work name
  (`🌿 fix/prune-worktrees`) replaces the branch: Claude Code reads it from the record beside
  the worktree its folder is in, Antigravity (its folder stays the main checkout) from the
  guard's record of the session, found by the payload's `session_id`. Once the worktree is
  gone the branch shows again.
- **Line 2:** the context left, from the CLI's own percentage, `?` before the first reply.
  **Line 3:** the rate-limit windows (Claude: the 5-hour then the 7-day window, with no label, and
  the spend limit as `spend`; Antigravity: its quota buckets by name) and the cost, each when the
  CLI sends it; no line when it sends neither. A window shows the share
  used and the local time it resets, with the weekday when that is not today; a window whose
  reset has passed is left out. The figures are those of the session's last API response: the
  CLI re-runs the script on changes in the session and at each reset time, not on a clock, so
  they can lag what other sessions have spent since.
- **Behind a gateway** such as Magpie, Claude Code signs in with `ANTHROPIC_AUTH_TOKEN` and sends
  no `rate_limits`: it sends them for a claude.ai sign-in only. With neither `rate_limits` nor
  `quota` in the payload and `ANTHROPIC_BASE_URL` on this machine (`127.0.0.1`, `localhost`,
  `::1`), the script asks the gateway's quotas route instead (`GET /v1/magpie/quotas`, no key):
  the account of the provider the model names (`codex/…`), Claude's for a model with no
  provider, the one that answered last for a routing group (`group/…`). Its `5 hours` and
  `7 days` show with no label; other windows keep the gateway's names
  (`7 days · Fable 45% → Thu 08:00`). A gateway on another machine is never asked, and one that
  does not answer within 0.3 s shows nothing. Each refresh asks anew.
- **Codex** runs no script: `tui.status_line` lists its own items (`current-dir`, `git-branch`,
  `model-with-reasoning`, `codex-version`, `context-remaining`, `five-hour-limit`,
  `weekly-limit`) and cannot follow a steered session, so its footer keeps showing the main checkout: **a gap, not emulated**. Instead
  worktree-guard answers the session's next tool call after a worktree is made or deleted with
  a one-line notice (a `systemMessage`, Codex's own channel for a line to the person: native, not a
  shim): `fix/x works in <path>`, then `fix/x is deleted; the
  session is back in <repo>`. The notice comes with the next call, not the moment the worktree
  changes, so a deletion by `ship-pr` is told only if the session makes another call.
  The two limit items are the share left of the account's primary and secondary usage limit,
  each omitted when there is none (a free plan has one 30-day window, shown by the first); they
  fill in behind a gateway too, since Codex reads them from its own responses.
  **Pi**'s built-in footer already shows the folder, branch, model, thinking level, context and
  cost; the Pi extension (`scripts/agent_hooks.ts`) adds a footer status, `worktree`, with the
  work name, set and cleared by the same next-call answer. A resumed Pi session shows it after its
  worktree next changes.
- The script never fails: bad input prints what it can and exits 0. `ai-dotfiles check` runs
  it once. An uninstall removes the two `statusLine` keys, which would otherwise run a command
  that is gone.

## Herdr

Herdr (`brew install herdr`) is a terminal multiplexer for coding agents: a background server
owns the panes and knows which agent runs in each, and its CLI lets one agent split a pane,
start another agent there, prompt it, wait on it and read its output. This repo carries the
`herdr` skill and the `herdr-title` hook, which labels each agent's row in Herdr's sidebar.
Herdr itself, its integrations and `~/.config/herdr/config.toml` are set up by hand on each
Mac: Herdr owns those files, and not every Mac runs it.

- **The skill is a pointer.** `skills/herdr/` tells the agent to load `herdr --skill`, the skill
  the installed binary prints, so its text always matches the version on that Mac (it changes
  between releases). It adds one rule: in a repo with the flow switch on, a spawned agent starts
  in the main checkout and makes its own worktree, because worktree-guard gives each worktree to
  one session. `herdr worktree` makes worktrees outside `.claude/worktrees/`, which the guard
  leaves alone, so the skill names `ai-dotfiles worktree new` instead.
- **Integrations, once per Mac:** `herdr integration install pi`, then `claude`, `codex` and
  `antigravity-cli`. Pi's is an extension, `~/.pi/agent/extensions/herdr-agent-state.ts`, that
  reports Pi's state (working, idle, blocked), which `herdr agent prompt --wait` waits on. The
  other three are a hook script plus Herdr's own entries in the CLI's hook file (Codex also gets
  `[features] hooks = true` in `config.toml`, and asks for the hook's approval in `/hooks`). They
  report the session, so a pane comes back in it after a server restart; Herdr still reads those
  three CLIs' state off the screen. The hooks step finds its own entries by their command and
  leaves Herdr's alone. `herdr integration status` lists them and their versions;
  `herdr integration uninstall <cli>` takes one out.
- **Upgrade:** `brew upgrade herdr`, then install the integrations again so their versions match
  the new binary. The running server keeps the old binary until it restarts (`herdr status`
  shows it). A restart stops every pane's process, the agent's that asked included, so the person
  does it from a terminal outside Herdr, once the integrations are in.

### Titles in the sidebar

```text
◐ herdr-title-hooks               the tab's name
  execute › wait › ask            the label: type › status › result
  AI-Config · claude              the space, then the CLI
```

Each agent's row carries a **label** in three layers. The **type** says what your prompt is
for, one of ten: grill, plan, study, execute, debug, review, explain, note, git, clean. The
**status** says whose move it is: `run` is the agent's, `wait` is yours, `idle` is nobody's.
The **result**, only under `wait`, says what the move is: `ask` (answer it), `allow` (a
permission dialog), `fail` (an error or a usage limit), `done` (finished, not looked at yet).
A bare `wait` means the hook cannot tell why. `config/herdr-title.json` lists the types with
their meanings, and the words.

- **How a label gets there.** `skills/herdr-title/scripts/herdr_title.py` runs at each prompt,
  turn end and session end in Claude Code, Codex and Pi, and at what only some of them hand
  over: dialogs (Claude Code; Codex's permission dialog), API errors (Claude Code), resumes
  (Claude Code, Pi) and interrupts (Codex). It keeps a mode per session and reports one label
  for each state Herdr detects: `herdr pane report-metadata <pane>
  --source user:ai-dotfiles-title --agent claude --state-label 'working=execute › run'
  --state-label 'done=execute › wait › done' ...`. Herdr shows the label of the state it sees,
  so a label changes with no further hook. The labels name the agent, so Herdr drops them when
  it exits. Outside Herdr the hook does nothing.
- **Who sets the type.** A command word (`approve`, `approve 57`) or a named skill (`/grilling`,
  `$tutor`, `/zkfy:zk-note`) sets it at once. Any other prompt goes to Haiku, and the type lands
  about 3 s later; the row keeps the type it had until then. Half the prompts are short answers
  such as `1` or `y`, so the model also reads the end of the agent's last message.
- **Who sets the result at a turn end.** A reply whose last line ends with a question mark, or a
  Codex plan block, reads `ask` at once. An API error, Pi's error or Claude Code's usage-limit
  note reads `fail` at once. Any other reply keeps `run` while Haiku reads its last 800
  characters and answers ask, wait or done. Wait counts only while Claude Code lists work of a
  `background` type (agents, workflows, teammates, cloud sessions, MCP tasks, monitors) or a
  scheduled prompt; a background command may be a server that never ends, so it does not count.
  On 191 real turn endings it was right 91% of the time, and its mistakes lean to calling a
  finished job an ask.
- **Dialogs.** A permission dialog reads `allow`. A question dialog, a plan to approve and an
  MCP form read `ask`. A subagent's permission dialog opens in your pane, so it counts.
- **What leaves a label as it is.** A prompt you did not type (a report, another session's
  message, a scheduled prompt firing: a `/loop` tick, a cron, a wake-up) keeps the type; an open
  ask stays through the turn that prompt starts, while a failure gives way to it. Each stop keeps
  the session's scheduled prompts, which is how the hook knows one when it fires; a prompt you
  type that says exactly the same counts as one. Only the session you last typed into labels its
  pane: a teammate in Claude Code's agent-team tmux server and a headless `claude -p` started
  from the pane change nothing.
- **Rows that need you go on top.** A row that waits for your answer, failed, or got no verdict
  from the model (a bare wait) carries a pane token, `need`, until a report or the session's end
  clears it. Codex's bare wait from a prompt to its stop hook carries none: it starts while Codex
  works. At each typed prompt, stop and resume the hook sets Herdr's agent view, "needs you",
  through Herdr's socket: those rows first, then Herdr's own attention order. Herdr 0.9.5 has no
  command for agent views. A view ends when the server exits, and the next typed prompt sets it
  again.
- **The model call** is `claude -p --model haiku` with no tools, no saved session, no user
  settings (so no hooks, plugins or MCP servers) and no `HERDR_*` variables. The hook starts it
  in a process of its own and does not wait, so a prompt is never delayed. One call takes about
  3 s and 700 input tokens, on the Claude login; about three of every four turn ends need one.
  Codex and Pi sessions use the same call, so they need `claude` installed, as the daily pass
  does.
- **The sidebar, once per Mac, by hand.** Herdr's default rows show no label. In
  `~/.config/herdr/config.toml`, set `status_indicators` in the `[ui]` table and replace the
  `rows` key in `[ui.sidebar.agents]`; add a table only if the file lacks it, since TOML refuses
  one declared twice. Then run `herdr server reload-config`:

  ```toml
  [ui]
  status_indicators = "symbols"

  [ui.sidebar.agents]
  rows = [
    ["state_icon", { token = "tab", fg = "#abb2bf", bold = true }],
    [{ token = "state_text", rules = [{ contains = "› done", fg = "#98c379" }, { contains = "idle", fg = "#98c379" }, { contains = "wait", fg = "#e06c75", bold = true }, { contains = "run", fg = "#e5c07b" }, { contains = "working", fg = "#e5c07b" }] }],
    ["machine", "workspace", "agent"],
  ]
  ```

  Row 1 is the icon and the tab's name, row 2 the label, row 3 the space and the CLI. The rules
  color the label by whose move it is, in three colors: red for yours (`ask`, `allow`, `fail`, a
  bare `wait`), yellow for the agent's (`run`), green for nobody's (`done`, `idle`). The `› done`
  rule stands before `wait`, since a done label holds both words. The colors are the one-dark
  theme's. The rules repeat the label's words, so a renamed word changes both places. Without
  these lines the labels are reported and not drawn; a row nothing has labeled shows Herdr's own
  word, `idle` or `working`, in the same green and yellow.
- **Limits.** Antigravity has no hook for a submitted prompt, so its rows keep Herdr's own word.
  Codex runs the new hooks only after approval in `/hooks`; until then a Codex stop reads a bare
  `wait`. Codex has no error event, so a failed Codex turn reads as done. In Claude Code, Esc
  and a question dialog closed without an answer fire no hook; Herdr then shows idle. A dialog
  no hook announces, later in the same turn, keeps the earlier dialog's word. A Stop hook that
  makes Claude Code go on after a question (`/goal` is one) leaves `wait › ask` on the row while
  it works, until the next stop. That a scheduled prompt reaches the hook as the text its stop
  listed is read off transcripts, not seen at the hook; an autonomous `/loop` (given no prompt)
  fires with other text than it lists, so it likely reads as typed. Three rows per agent fit
  about 3 agents at the default split in a 27-row window; drag the divider between spaces and
  agents for more. Herdr keeps no labels across a restart of its server; a resumed Claude Code
  or Pi session reports its kept state again, and a Codex pane waits for its next typed prompt.
- **Changing it.** The types, the words, the rules that decide at once and both model
  instructions are in `config/herdr-title.json`, which the hook reads on every call;
  `scripts/tests/test_herdr_title.py` checks the file. State is one small file per session under
  `~/.local/state/ai-dotfiles/herdr-title/` (`$HERDR_TITLE_STATE` moves it); `panes/` there
  holds the session each pane belongs to.

## Small commits

A hook on every shell command gates `git commit` (PreToolUse on Bash / `run_command`; Pi
through `scripts/agent_hooks.ts`, which sends each event to the door). There is no rule text
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
- **Declared in its `feature.json`:** PreToolUse for the shell tools of every CLI. The door
  runs it after worktree-guard, from the one PreToolUse entry per CLI the hooks step writes.
  State, the sizes a session was warned about, is in `~/.local/state/ai-dotfiles/small-commits/`.
  A cloud session on this repo runs it through the door, from `.claude/settings.json` (Cloud
  sessions).

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
  prune-branch/  ai-dotfiles git prune     base pulled; branch deleted here and on origin; then its worktree
  approve/       ai-dotfiles approve       preflight, then the six above, in that order
  ship-pr/       ai-dotfiles ship-pr       an agent's finish: checks, push as <type>/<slug>, PR, worktree deleted
```

- **Steps:** preflight (a branch other than the base, no tracked changes), then the six.
  Each is skipped when done, so a stopped run is rerun as is; nothing is undone on failure.
  Each step's skill holds the fix for its own stops.
- **By number:** `ai-dotfiles approve <n>` lands PR n from any session, with no local branch or
  worktree: reviewer approval, archive tag at the PR head, merge commit, remote branch deleted,
  then the main checkout fast-forwarded only when git can without touching uncommitted files
  (never a stash or reset; otherwise skipped, with the reason). Each step is skipped when done.
  Run in PR n's own linked worktree, it ends that worktree too, as below.
- **The end:** run in the linked worktree that holds the work, either form leaves only the
  archive tag: the branch deleted, the main checkout fast-forwarded, then the worktree deleted,
  last (nothing can run in its folder after it), through worktree-guard, so its record, its
  owner and the session's binding go too. It is kept, as a `skipped:` line, in a repo whose
  flow is off, when the guard did not make it, while another live session owns it, or while it
  holds uncommitted files or a commit on no remote. A worktree holding other work is untouched;
  by number, so is the PR's own while it holds uncommitted files or commits the PR lacks.
- **Ship:** `ai-dotfiles ship-pr` is the agent's own finish, before the person reviews: in the worktree
  `worktree new` made (no branch) it runs the checks (the commands of the repo's `AGENTS.md`
  Verify block), pushes HEAD as `<type>/<slug>`, opens the PR and deletes the worktree. It stops
  with no Verify block unless `--no-checks`, and, for a worktree whose name is not
  `<type>/<slug>` (made by `claude -w` or a subagent), unless `--work <type>/<slug>` names the
  branch. In a worktree `worktree pr <n>` made it pushes to that PR's own branch, fast-forward
  only, and opens no PR. It makes no archive tag: `approve <n>` tags the PR's head.
- **The reviewer:** GitHub refuses self-approval, so each repo names its own reviewer login,
  cached in `git config --local approve.reviewer`. None cached: exit 3, and the agent asks
  the user and reruns with `--reviewer LOGIN`. A login is cached only once it has a `gh auth`
  token, is not the PR's author, and can read the repo. The script never invites an account;
  `ai-dotfiles git reviewer [LOGIN | --unset]` shows, sets or clears it.
- **The record:** an annotated `archive/<branch without its first segment>` tag at the branch
  tip, pushed before the merge commit, in the one format `archive-tag` owns: the commits' date
  span, the PR title, "merged and deleted", and a `PR:` line. A name taken by another commit
  gets the date; a tag already at the tip is reused.
- **`--dry-run`** prints each change it would make; read-only commands still run. A dry run of
  `approve <n>` fetches nothing, since a fetch writes refs.

## Cloud sessions

A cloud session is Claude Code on a fresh Ubuntu VM that Anthropic runs: claude.ai/code, the
phone's Code tab, `claude --cloud`. It reads three things: the repo's clone, the cloud
environment set on claude.ai (setup script, variables, network level) and the claude.ai account
(its synced skills and connectors). Nothing `ai-dotfiles install` writes on a Mac reaches it:
`~/.claude`, `~/.claude.json` and `~/.local/bin` stay on the Mac. A cloud session on this repo
gets its setup from the committed `.claude/settings.json`:

```text
.claude/settings.json   two hooks, each run only when CLAUDE_CODE_REMOTE is true
  SessionStart          scripts/cloud_session.py start:
                          the global rules (config/global-agents.md) as context;
                          each skill linked into .claude/skills/ (relative links into skills/,
                            ignored by git), all but config/cloud.json's local_only, then
                            reloadSkills (Claude Code 2.1.152 or later);
                          scripts/ first on PATH through CLAUDE_ENV_FILE, so ai-dotfiles runs
  PreToolUse on Bash    the door (ai-dotfiles hook), which runs the cloud features: small-commits
```

- **On a Mac nothing changes.** The gate is false there, so only the user-level hooks run and
  no `.claude/skills/` is made. Links committed to the repo would list every skill again in each
  linked worktree, a folder below the main checkout; so they are made in the cloud clone only. A
  part of `start` that fails is named in the session's context. `scripts/tests/test_cloud.py`
  runs both hooks against a temporary clone.
- **Gaps, documented rather than emulated:**
  - **One repository, outside Projects:** a session with several repositories, or a thread in a
    claude.ai Project, runs none of the repo's hooks, so it gets none of the above; a Project
    thread does not read `.claude/skills/` either.
  - **GitHub:** the session's GitHub proxy refuses `gh pr` and `gh issue` (GraphQL), tag pushes,
    branch deletes and repositories the session is not on; `gh api` REST works on its own repo.
    So the git steps stay on the Mac: a cloud session pushes its `claude/…` branch, the session's
    Create PR opens the PR, and `approve <n>` lands it. The skills that use the GitHub tracker
    (to-spec, to-tickets, triage, wayfinder, implement-spec, spec-review) reach issues through
    `gh api` only.
  - **The Mac's own:** daily-log, Herdr, worktree-guard (a cloud session already works alone on
    its branch), Codex, Pi, Antigravity, LSP plugins, Claude in Chrome and computer use.
  - **Plugins and MCP:** a cloud session installs no plugins from its settings. They load through
    `CLAUDE_CODE_PLUGIN_DIRS`, which the environment below sets up. context7 is added to the VM's
    `~/.claude.json` there, but the Trusted network level does not allow its host.
  - **Settings:** user settings are not read. Set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` on the
    environment, and pick `/model` and `/effort` per session (`CLAUDE_CODE_EFFORT_LEVEL` would
    override `/effort` in every session). Whether `/advisor` works in the cloud is unverified.
  - **Network:** a new environment's network level is Trusted ("Limited" in the dialog): package
    registries and GitHub. Other hosts answer `403 host_not_allowed` until the level is Custom or
    Full.
- **Every repository, through the cloud environment.** A cloud environment's setup script gives
  every session started in it the Mac's setup, whatever the repo. Paste `scripts/cloud/environment.sh`
  as the setup script of the environment the sessions use (here, Default), and set the variable the
  report's last line gives: `CLAUDE_CODE_PLUGIN_DIRS=/opt/ai-plugins/web-clipper:/opt/ai-plugins/zkfy`.
  The script clones this repo to `/opt/ai-dotfiles` and runs `scripts/cloud/setup.sh`:

  ```text
  install.sh --cloud  ~/.claude/CLAUDE.md, the settings keys, context7, the skills config/cloud.json
                      does not keep local, small-commits' hook; no plugins step, no launchd
  ai-dotfiles         linked into /usr/local/bin
  plugins             each one config/plugins.json gives Claude, at its release tag, in /opt/ai-plugins;
                      then the plugin's own cloud/setup.sh, with every pin as <NAME>_REF
  report              /opt/ai-dotfiles-setup.txt, ok or FAIL per step; the setup never fails a session
  ```

  - **When changes arrive.** The setup's result is cached for about a week. A change on `main`
    reaches new sessions within that week, or at once after any edit of the environment's setup
    script.
  - **What the spike settled** (jasonsie/ai-dotfiles#80):
    - a setup script clones public repos but not private ones, which is why this repo is public;
    - the session loads what the setup writes into the VM's `~/.claude`;
    - plugins load through `CLAUDE_CODE_PLUGIN_DIRS`.
  - **A session on this repo** in that environment also runs the repo's own hooks. The rules come
    twice, the commit gate runs twice with one verdict, and each skill loads once (personal over
    project).
  - **Platforms.** This amends ADR-0005 Q3 (macOS only): a cloud session's Linux VM is a second
    platform, for Claude Code alone. launchd and the healthcheck's launchd check step aside off
    macOS.
- **Remote Control has no gaps:** the phone drives a session on the Mac, with every tool, while
  the Mac is awake.
- **Check a session:** paste this probe into a cloud session on this repo. On another repo, ask for
  `cat /opt/ai-dotfiles-setup.txt` and `ls ~/.claude/skills | wc -l`.

  ```text
  Cloud probe for ai-dotfiles. Push nothing. Answer as one table (item, result):
  1. echo "$CLAUDE_CODE_REMOTE"; claude --version; command -v ai-dotfiles gh python3
  2. Is "Report to me telegraphically" in your context? Is AGENTS.md?
  3. ls .claude/skills | wc -l; can you invoke grilling, which-skill and tdd? Is approve absent?
  4. Which MCP servers and plugins do you have? The advisor, Workflow and agent-team tools?
  5. gh api repos/jasonsie/ai-dotfiles -q .full_name ; gh pr list   (expect the second to 403)
  6. curl -s -o /dev/null -w '%{http_code}\n' https://context7.com https://example.com
  7. Run `git commit --allow-empty -m probe`: the small-commits hook should block it. If it
     commits, run `git reset --soft HEAD~1` and say "hook missing".
  ```

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
- **Flow switch:** the repo-local git config `worktree-guard.flow`, toggled by the person's
  `/worktree-flow` once they click OK in its macOS dialog; no agent and no prompt the person did
  not type can click it, and the guard refuses an agent's `git config` write of the key. A repo
  that is off gets nothing from the guard. Claude's `WorktreeCreate` hook still runs there, only to
  reproduce Claude's own default (a branch `worktree-<name>` from the session's HEAD).
- **Work name:** `<type>/<slug>` (for example `fix/prune-worktrees`), what a task is called. It
  names the worktree folder (`fix-prune-worktrees`) and, when shipped, the branch and the PR.
- **First-edit gate:** in a repo that is on, a session's first edit in the main checkout is
  stopped with "name this work"; `ai-dotfiles worktree new <type>/<slug>` makes the worktree, and
  the edits go there. Only the main checkout and `.claude/worktrees/` are gated or claimed.
- **Ship:** an agent's finish in its worktree (`ai-dotfiles ship-pr`): checks, push, PR, worktree
  deleted. The person's `approve <n>` follows.
- **Leftover:** a linked worktree whose owner is gone. One with nothing to lose is deleted when a
  worktree is made or a session ends; one holding uncommitted files or unpushed commits stays,
  listed as LEFT BEHIND, until a session takes it over or `worktree rm` drops it.
- **Label:** the line on an agent's row in Herdr's sidebar, type › status › result: what the
  prompt is for, whose move it is, and what the move is when it is the person's
  (`execute › wait › ask`). The `herdr-title` hook sets it; see Herdr.
- **Cloud environment:** the claude.ai settings a cloud session runs in: network level, variables and
  setup script. `scripts/cloud/environment.sh` is this repo's setup script.
- **Cloud session:** Claude Code on a VM Anthropic runs (claude.ai/code, the phone's Code tab,
  `claude --cloud`). It reads the clone, the cloud environment and the claude.ai account, never a
  Mac's home folder; see Cloud sessions.
