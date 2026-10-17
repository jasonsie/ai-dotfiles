# How it works

This repository is the single source of the owner's global AI CLI setup. You edit
sources here; scripts apply them to each CLI's native folders; a healthcheck reads the
live state back. Decisions: [ADR-0005](adr/0005-global-config-single-source.md),
[ADR-0006](adr/0006-redesign-round-2.md).

## The flow

```text
YOU EDIT                          APPLIED BY (bash scripts/install.sh --apply)    LANDS IN
tools/instructions/AGENTS.md  ─►  install-global-instructions.py (symlinks)  ─►  each CLI's global instruction file
tools/settings/managed.json   ─►  apply-settings.py (merges listed keys)     ─►  settings.json / config.toml
tools/mcp/servers.json        ─►  apply-mcp.py (native `mcp add`)            ─►  Claude Code, Codex
zkfy checkout (ZKFY_DIR)      ─►  install-vault-knowledge.py (links)         ─►  query skill, vault-knowledge launcher
skills/<name>/                ─►  install-skills.py (links)                  ─►  every CLI's skill folder
                                  scripts/healthcheck.sh checks the live state

WEEKLY  GitHub Action ─► sync-cli-docs.sh + report-upstream.py ─► upstream/ on branch upstream-sync ─► review PR
```

`install.sh` previews by default and writes only with `--apply`; `--target=claude|codex|pi|agy`
limits a run. Each step is idempotent: a second run reports 0 changes.

## Where each CLI reads things

| | Claude Code | Codex CLI | Pi | Antigravity (CLI and IDE) |
|---|---|---|---|---|
| Global instructions | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `~/.pi/agent/AGENTS.md` | `~/.gemini/GEMINI.md` |
| Project instructions | `CLAUDE.md`; `AGENTS.md` when no `CLAUDE.md` exists | `AGENTS.md` | `AGENTS.md`, else `CLAUDE.md` | `AGENTS.md`, `GEMINI.md` |
| User skills | `~/.claude/skills` | `~/.agents/skills` | `~/.agents/skills`, `~/.pi/agent/skills` | `~/.gemini/config/skills` |
| Settings file | `~/.claude/settings.json` | `~/.codex/config.toml` | `~/.pi/agent/settings.json` | `~/.gemini/antigravity-cli/settings.json` |
| MCP registered here | yes | yes | not yet (Pi has MCP) | not yet |

Checked at runtime on 2026-10-16 and 2026-10-17: every CLI loads the global file and a
project `AGENTS.md`, and lists the `grilling` and `query` skills. Codex can be checked
without a model call: `codex debug prompt-input "hi"` prints what it would send.

## Principles

- **Shared behavior, native differences.** The same intent reaches each CLI through its
  native surface. A missing capability is documented, never shimmed.
- **Link what is read-only; merge what a CLI writes.** Instruction files and skills are
  symlinks to one source. Settings files are never linked, because each CLI writes its
  own state into them; only listed keys are merged.
- **Global only what applies everywhere.** The global `AGENTS.md` is loaded into every
  session of every project, so it holds only rules true in every repository and every
  CLI. Everything else lives in a project's `AGENTS.md` or in a skill, which loads on demand.
- **Never write through a link.** A CLI's memory or rule-saving feature must not edit the
  shared file; `~/.gemini/config/AGENTS.md`, where Antigravity appends rules, is never linked.
- **Portable across Macs.** No usernames, checkout paths, or Homebrew prefixes in `tools/`
  or `scripts/`; scripts resolve their own location. The healthcheck enforces this.
- **Safe by default.** Preview unless told otherwise, idempotent, back up before writing,
  refuse to overwrite anything a script did not create, and roll back on failure.

## Settings: enforce and default

`tools/settings/managed.json` (version 2) lists, per CLI, an `enforce` group and a
`default` group. `enforce` holds safety settings (approval policy, sandbox, permission
prompts) and is put back on every install. `default` holds model choices and is written
only while a CLI has no value; a model you pick in a CLI's own menu stays, and the preview
and healthcheck report it as a "local choice kept".

## Memory

- **Task memory:** a task that spans sessions keeps its state in `docs/plans/<task>.md`
  in its repository (the global rule), so another session or CLI can continue it.
- **Project memory:** the project's `AGENTS.md`, read natively by every CLI. When a
  project also has a `CLAUDE.md`, it links to `AGENTS.md` or imports it with `@AGENTS.md`.
- **Knowledge:** the CS vault, read through the `query` skill (read-only). Saving to the
  vault needs an explicit request.
- **Claude's auto memory** stays on as a per-machine, Claude-only scratchpad.

## Upstream updates

- `scripts/sync-cli-docs.sh` mirrors each CLI's official docs into `upstream/docs/<tool>/`
  (claude, codex, pi, antigravity). Each source has a page floor; below it, the previous
  copy is kept and the run fails, so a moved index cannot wipe a mirror.
- `scripts/report-upstream.py` writes the pull request description: pages changed per
  tool; changes that touch this setup (managed setting keys, instruction files, skill
  folders, MCP); picked skills that changed upstream since their pinned commit; and skills
  new in the watched collections (`upstream/catalogs.json`).
- A skill adapted from another repository is pinned in `skills/skills.lock` (repository,
  path, commit, license, local edits). When the report shows it changed upstream, compare
  the upstream diff with the local copy, adopt what you want, and update the pinned commit.

## Backups and rollback

| Step | Record | Rollback |
|---|---|---|
| Instructions | `~/.local/state/ai-cli-workspace/global-instructions/backup-*/manifest.json` | Remove the link, copy the backup back with `cp -Pp` |
| Settings | `~/.local/state/ai-cli-workspace/settings/backup-*` | Copy the backed-up file back |
| Skills | `~/.local/state/ai-cli-workspace/skills.json` (links this repo created) | Delete a skill folder and rerun with `--apply` |
| Vault tooling | `~/.local/state/zkfy/integration.json` | `python3 scripts/install-vault-knowledge.py --uninstall --apply` |

## Glossary

- **Source:** a file under `tools/` or `skills/` (or the zkfy checkout) that an installer
  applies. Edit the source, never the destination.
- **Managed key:** a settings key in `managed.json`, either `enforce` or `default`; every
  other key belongs to the CLI or to you.
- **Local choice:** a `default` key whose live value differs from `managed.json`; kept on purpose.
- **Mirror:** a machine-written copy of upstream docs under `upstream/`; never edit it by hand.
- **Floor:** the minimum number of pages a source must yield before its mirror is replaced.
- **Receipt:** a record of what a script created, so it never touches anything else.
- **Emitted vs verified:** writing a config is not proof that it works. Verified means the
  CLI itself reports it (`mcp list`, a session listing the skill, `codex debug prompt-input`).
