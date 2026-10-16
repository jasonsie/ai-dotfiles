# Project Context

## What

`ai-cli-workspace` is the **single source of global AI CLI configuration** for the
owner's Macs: Claude Code, Codex CLI, Gemini CLI, and Pi. It owns four things —
shared instructions, a small set of must-match settings keys, shared MCP servers,
and the binding to the zkfy knowledge vault — and nothing per-project.
Decided in [ADR-0005](docs/adr/0005-global-config-single-source.md), which supersedes
the full-parity goal of [ADR-0002](docs/adr/0002-multi-cli-parity-target.md).

## Principles

- **Shared behavior, native differences.** The same intent reaches every CLI where it
  has a native surface. Missing capabilities (e.g. Pi has no MCP) are documented, not
  shimmed.
- **Link what is read-only, merge what the CLI writes.** Instruction files are
  symlinks to one source. Settings files are never symlinked; only managed keys are
  merged in, because each CLI writes its own runtime state back to them.
- **Portable across Macs.** No usernames, checkout paths, or Homebrew prefixes in
  `tools/` or `scripts/`; the installer resolves its own location.
- **Safe by default.** Dry-run unless told otherwise, idempotent, backup before
  write, refuse to overwrite what it does not own, roll back on failure.

## Language

**Source**: a file under `tools/` (or the zkfy checkout for vault tooling) that an
installer applies. Edit the source, never the destination.

**Managed key**: a settings key listed in `tools/settings/managed.json`. The
installer sets it; every other key in that settings file belongs to the CLI or the
user.

**Emitted vs verified**: a config being written is not proof it works. "Verified"
means the CLI itself reports it (`<cli> mcp list`, a session loading the
instructions). The healthcheck checks live CLI state for this reason.

**Retired generator**: the earlier per-project rule/hook/agent compiler (`tools/rules`,
`tools/hooks`, `rules.sh`, `init-project.sh`). Removed by ADR-0005; its design notes
remain in `docs/archive/`.

## Cross-CLI surfaces

| Concept | Claude Code | Codex CLI | Gemini CLI | Pi |
|---|---|---|---|---|
| Global instructions | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `~/.gemini/GEMINI.md` | `~/.pi/agent/AGENTS.md` |
| Settings | `settings.json` | `config.toml` | `settings.json` | `settings.json` |
| User MCP | `~/.claude.json` via `claude mcp add -s user` | `config.toml` via `codex mcp add` | `settings.json` via `gemini mcp add -s user` | none |
| Skills | `~/.claude/skills/` | `~/.agents/skills/` | `~/.gemini/skills/` or `~/.agents/skills/` | `~/.pi/agent/skills/` or `~/.agents/skills/` |
