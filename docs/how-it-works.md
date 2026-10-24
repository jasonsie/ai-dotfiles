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
  upstream-docs.json   the documentation sources mirrored into docs/upstream/
skills/              shared skills; skills.lock pins adapted ones
scripts/             ai-dotfiles, install.sh, uninstall.sh, healthcheck.sh (entry points)
  install/             installer.py (shared by every step) and one file per step
  upstream/            the weekly docs sync and its pull request report
  tests/               unit tests for all of the above
docs/
  how-it-works.md      this file
  onboarding.md        this repo's report from /onboard
  upstream/            machine-written mirrors of upstream docs, their indexes, and the skill catalogs
```

## The flow

```text
YOU EDIT                          APPLIED BY scripts/install/ (ai-dotfiles = install.sh)   LANDS IN
config/ai-clis.json           ─►  every step: which CLIs, and their paths  ─►  (the CLIs switched on)
config/global-agents.md       ─►  instructions.py (symlinks)               ─►  each CLI's global instruction file
config/cli-settings.json      ─►  settings.py (merges listed keys)         ─►  settings.json / config.toml
config/mcp-servers.json       ─►  mcp.py (native `mcp add`, or a merge)    ─►  Claude Code, Codex, Pi, Antigravity
skills/<name>/                ─►  skills.py (links)                        ─►  every CLI's skill folder
scripts/ai-dotfiles           ─►  skills.py (link)                         ─►  ~/.local/bin
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
instructions, settings, MCP servers and skills. Paths start with `~/`. The file is checked strictly: a
missing or unknown key, an `on` that is not `true` or `false`, or a CLI the steps have no
code for stops the run.

- **The file is the desired state.** A run installs for each CLI switched on and takes out
  of each CLI switched off what this repo put there: the instruction link (the original
  comes back) and skill links. Settings keys and MCP servers stay, as with any uninstall.
  A CLI switched off gets no folders created.
- **A shared folder stays while any CLI that is on reads it** (`~/.agents/skills`, for
  Codex and Pi).
- **`--target` only narrows a run** to one CLI; `all` means every CLI in the file, on or
  off. `uninstall` removes for every selected CLI whatever its switch.
- **How each CLI's files are edited stays in code:** Codex settings are TOML, and each CLI
  has its own `mcp add`.

`uninstall.sh` runs each step's `--uninstall` in reverse order and removes whatever points
into this repo: instruction links (restoring the file from before the first install),
skill links and the command link. Settings keys and MCP
servers stay and are listed, because they hold no repo paths and could be the user's own.
After it, deleting the repo breaks nothing.

## Where each CLI reads things

| | Claude Code | Codex CLI | Pi | Antigravity (CLI and IDE) |
|---|---|---|---|---|
| Global instructions | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `~/.pi/agent/AGENTS.md` | `~/.gemini/GEMINI.md` |
| Project instructions | `CLAUDE.md`; `AGENTS.md` when no `CLAUDE.md` exists | `AGENTS.md` | `AGENTS.md`, else `CLAUDE.md` | `AGENTS.md`, `GEMINI.md` |
| User skills | `~/.claude/skills` | `~/.agents/skills` | `~/.agents/skills`, `~/.pi/agent/skills` | `~/.gemini/config/skills` |
| Settings file | `~/.claude/settings.json` | `~/.codex/config.toml` | `~/.pi/agent/settings.json` | `~/.gemini/antigravity-cli/settings.json` |
| MCP servers | `~/.claude.json` via `claude mcp add` | `config.toml` via `codex mcp add` | `~/.pi/agent/mcp.json` via `pi mcp add` | `~/.gemini/config/mcp_config.json`, merged (no `mcp add`) |
| MCP server guidance | server instructions | server instructions | only the `description` in `mcp-servers.json` | not documented |
| Explicit-only skill | `disable-model-invocation: true` | `agents/openai.yaml`: `policy.allow_implicit_invocation: false` | `disable-model-invocation: true` | none documented; may load implicitly |

The installers read the paths in the first five rows from `config/ai-clis.json`. To move
a CLI's folder, edit its paths there; `CLAUDE_CONFIG_DIR`, `CODEX_HOME` and
`PI_CODING_AGENT_DIR` are never read for paths, and a run warns when one is set and
disagrees with the file.

Checked at runtime on 2026-10-16 and 2026-10-17: every CLI loads the global file and a
project `AGENTS.md`, and lists the `grilling` skill. Codex can be checked
without a model call: `codex debug prompt-input "hi"` prints what it would send.

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
  The one deliberate exception is the `house-style` skill, which rewrites its `STYLE.md`
  in this repo on a branch, for review before merge.
- **Portable across Macs.** No usernames, checkout paths, or Homebrew prefixes in `config/`
  or `scripts/`; scripts resolve their own location. The healthcheck enforces this.
- **Safe by default.** `--dry-run` previews, idempotent, back up before writing,
  refuse to overwrite anything a script did not create, and roll back on failure. Every
  step writes through `apply()` in `scripts/install/installer.py`, so these rules live in
  one place.

## Settings: enforce and default

`config/cli-settings.json` (version 2) lists, per CLI, an `enforce` group and a `default`
group. `enforce` holds safety settings (approval policy, sandbox, permission prompts) and
is put back on every install. `default` holds model choices and is written only while a
CLI has no value; a model you pick in a CLI's own menu stays, and the preview and
healthcheck report it as a "local choice kept".

## Memory

- **Across sessions:** the `handoff` skill writes the session's state to a temporary file
  that another session or CLI picks up; nothing in a repository tracks tasks.
- **Project memory:** the project's `AGENTS.md`, read natively by every CLI. When a
  project also has a `CLAUDE.md`, it links to `AGENTS.md` or imports it with `@AGENTS.md`.
- **Claude's auto memory** stays on as a per-machine, Claude-only scratchpad.

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
| Settings | `~/.local/state/ai-dotfiles/settings/backup-*` | Copy the backed-up file back |
| MCP (Antigravity's file) | `~/.local/state/ai-dotfiles/mcp/backup-*` | Copy the backed-up file back |
| Skills, command | `~/.local/state/ai-dotfiles/skills.json` (links this repo created) | `python3 scripts/install/skills.py --uninstall` |
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
- **Emitted vs verified:** writing a config is not proof that it works. Verified means the
  CLI itself reports it (`mcp list`, a session listing the skill, `codex debug prompt-input`).
