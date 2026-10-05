# Shared global instructions

## Scope and source

`tools/instructions/AGENTS.md` is the single, CLI-neutral source for personal
cross-project instructions. The installer links it to:

| CLI | Native global entry |
| --- | --- |
| Claude Code | `~/.claude/CLAUDE.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` |
| Codex CLI | `~/.codex/AGENTS.md` |

The file contains no imports, provider-specific models, or workspace-maintainer
rules. Codex does not need to interpret Claude's `@` imports. Existing Claude
rules, skills, and plugins stay where they are; JSON/TOML settings, permissions,
MCP, credentials, and session histories are not merged or modified.

The repo-root `CLAUDE.md`, `GEMINI.md`, and `AGENTS.md` remain generated project
instructions. They are **not** suitable global defaults for unrelated projects.
The migration deliberately stops importing the entire workspace into every
Claude session. Project-specific Git automation and provider-specific guidance
remain project-scoped instead of being imposed globally.

## Install and update

From this checkout (Python 3.8+ required; no new dependencies):

```bash
bash scripts/install.sh --instructions-only --dry-run
bash scripts/install.sh --instructions-only
```

- `--target=claude|gemini|codex` limits the affected CLI; default is `all`.
- Missing entries, empty files, and the exact old Claude workspace pointer can
  migrate automatically. Existing files are backed up, including empty files.
- Unknown instructions or symlinks are refused before any entry changes. Read
  and reconcile their content first, then explicitly use `--replace-instructions`.
- Non-empty Codex `AGENTS.override.md` is refused because it shadows `AGENTS.md`.
- Full installs also install the shared entries. `--instructions-only` skips all
  settings/rules adapters; use it for this migration to avoid unrelated changes.
- Direct Python invocation defaults to dry-run:
  `python3 scripts/install-global-instructions.py --target all` (`--apply` writes).
  `--home /temporary/home` isolates installation and ignores config-dir overrides.
- Normal invocation honors `CLAUDE_CONFIG_DIR` and `CODEX_HOME`. The default
  Gemini entry is under the user home directory.

Keep the checkout at a stable path. Editing the shared source updates all three
links without regenerating copies. Start a new CLI session to load the changes.
Do not use memory commands or old bootstrap scripts to append project/session
state to these links: a write through any link changes the source for **all** CLIs.
The workspace session-start hook skips its legacy bootstrap for linked global
instructions and for non-Claude CLIs.

## Backups and rollback

Each changing install prints a private backup directory under
`~/.local/state/ai-cli-workspace/global-instructions/backup-*`. Its `manifest.json`
records the original kind and backup name for each destination. Files retain
permissions; symlinks retain their original link text. Originally absent entries
have a null backup. A failed install automatically restores entries it changed.
An unchanged reinstall creates no backup or filesystem changes.

For manual rollback, stop the affected CLIs, inspect that run's manifest, and
confirm each destination still points to the shared source. Remove **only the
entry symlink**, then copy its corresponding backup with `cp -Pp` to that exact
destination. For an originally absent entry, remove only the symlink. Never copy
or redirect text onto a linked entry without first removing the link.

## Verification and limits

```bash
python3 -m unittest discover -s tests -p 'test_global_instructions.py'
bash scripts/install.sh --instructions-only --dry-run
ls -l ~/.claude/CLAUDE.md ~/.gemini/GEMINI.md ~/.codex/AGENTS.md
```

The second command should report zero changes after installation. Tests cover
migration, backup restoration, rollback on failure, dry-run, idempotency, target
selection, collision/override guards, legacy-hook safety, and unrelated-file
preservation. They do not prove end-to-end model behavior.

For runtime verification, start each CLI in an unrelated project: use Claude's
`/context`, Gemini's `/memory show`, and ask Codex to identify its loaded global
instructions. Native discovery is documented in the checked-in mirrors:
`docs/claude/memory.md`, `docs/gemini/upstream/cli/gemini-md.md`, and
`docs/codex/upstream/agent-configuration/agents-md.md`. Codex's combined instruction
budget is finite (32 KiB by default); large project rules can still exhaust it.

## Design grounding

This implementation choice follows three recorded ideas in the CS vault:

- `333.ai/methodology/AI-Portable-Harness-Design.md#Single Truth`: one definition
  linked into each CLI prevents copy drift. Its `Memory Gradient` section also
  distinguishes global from repository-local context.
- `333.ai/llm/AI-LLM-Context-Management-Patterns.md#Give the Agent a Computer`:
  progressive disclosure keeps detailed references out of the resident context.
- `333.ai/agents/AI-Agent-Memory-Governance.md#Memory as Index`: keep durable
  context selective and check stale memories against current reality.

The exact installer, migration policy, and shared wording here are a local
implementation/synthesis, not claims that the vault verified CLI compatibility.
