# `tools/` — Canonical Source of Truth

> **Do not edit `.claude/`, `~/.gemini/`, or `~/.codex/` directly.** They are generated from this directory by `scripts/install.sh`. Edits here propagate to all three CLIs on next install.

## Layout

| Path | Contents | Format |
|------|----------|--------|
| `tools/skills/<name>/SKILL.md` | Cross-CLI skills (Claude/Gemini/Codex all read SKILL.md natively) | Markdown + YAML frontmatter |
| `tools/agents/<name>.md` | Portable agent specs (adapters wrap per CLI) | Markdown + YAML frontmatter |
| `tools/rules/<name>.md` | Cross-CLI rules. `manifest.yaml` marks which target each CLI | Markdown |
| `tools/rules/manifest.yaml` | Per-rule CLI targeting | YAML |
| `tools/commands/<name>.md` | Slash commands. Claude reads `.md`; Gemini wrapped as `.toml`; Codex skipped | Markdown + YAML frontmatter |
| `tools/mcp/servers.yaml` | MCP servers in neutral schema; adapters emit per-CLI native | YAML |
| `tools/hooks/<event>.sh` | Hook scripts; read `$WORKSPACE_CLI_NAME` to handle per-CLI differences | Bash |
| `tools/hooks/manifest.yaml` | Maps neutral event names to each CLI's native event name | YAML |
| `tools/settings/<cli>.{json,toml}.tmpl` | Per-CLI settings templates with `{{placeholders}}` | JSON / TOML |

## Generation flow

```
tools/skills/*          ──┐
tools/agents/*          ──┤
tools/rules/*           ──┤        scripts/install.sh
tools/commands/*        ──┼──►     ─ adapters/claude.sh   ──►  ~/.claude/*  + .claude/*
tools/mcp/servers.yaml  ──┤        ─ adapters/gemini.sh   ──►  ~/.gemini/*
tools/hooks/*           ──┤        ─ adapters/codex.sh    ──►  ~/.codex/*
tools/settings/*        ──┘        ─ adapters/rules.sh    ──►  AGENTS.md, CLAUDE.md, GEMINI.md
```

## Authoring rules

- **SKILL.md frontmatter**: `name` (≤64 chars), `description` (≤1024 chars). Body is markdown.
- **Agent frontmatter**: `name`, `description`, `model`, `color` (Claude convention; adapters translate).
- **Hook scripts**: must be idempotent. Use `$WORKSPACE_CLI_NAME` for CLI-specific branches. Use `$WORKSPACE_DIR` (set by all wrappers) instead of `$CLAUDE_PROJECT_DIR`.
- **Settings templates**: use `{{REPO_DIR}}`, `{{HOME}}`, `{{CLI_NAME}}` placeholders.

## Idempotency contract

Adapters must:
1. Detect existing state before writing.
2. Preserve user-added content (marked with `# managed by workspace` blocks).
3. Honor `--dry-run` (print intended changes, write nothing).
4. Print a summary at the end (created / updated / unchanged).
