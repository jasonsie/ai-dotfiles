# AI CLI Workspace

> 共用 AI CLI 指示與可攜能力庫。全域指示支援 Claude Code、Gemini CLI、Codex CLI、Pi；
> 完整設定 adapters 目前僅涵蓋前三者。設定有產出不代表已通過 runtime 驗證。

A shared instruction and capability library for Claude Code, Gemini CLI, Codex CLI,
and Pi. Forked from [zeuikli/claude-code-workspace](https://github.com/zeuikli/claude-code-workspace).
Project context lives in [`CONTEXT.md`](CONTEXT.md); cross-project instructions live
in [`tools/instructions/AGENTS.md`](tools/instructions/AGENTS.md).

## Shared global instructions

```text
tools/instructions/AGENTS.md
  ├── ~/.claude/CLAUDE.md
  ├── ~/.gemini/GEMINI.md
  ├── ~/.codex/AGENTS.md
  └── ~/.pi/agent/AGENTS.md
```

These are symlinks, not copies. Edit the source, never redirect output into a linked
entry file. Claude, Codex, and Pi custom config-directory environment variables are
respected. Instructions remain small; project rules and retrieved knowledge load
separately. Knowledge retrieval is read-only; saving knowledge requires permission.

```bash
bash scripts/install.sh --instructions-only --dry-run
bash scripts/install.sh --instructions-only
# Select one CLI:
bash scripts/install.sh --target=pi --instructions-only
```

Unknown existing instructions require review and `--replace-instructions`.
Migration backs up replaced files. See [migration and rollback](docs/global-instructions.md).
Pi supports instruction installation only, not a full settings/hooks adapter.

## Configuration layers — do not confuse them

| Layer | Source / destination | Scope |
|---|---|---|
| Shared instructions | `tools/instructions/AGENTS.md` → four native entry files | All projects |
| Claude workspace settings | `tools/settings/claude.json.tmpl` → **this checkout's** `.claude/settings.json` | This workspace, not global Claude preferences |
| Claude user settings | `~/.claude/settings.json` | User-owned models, plugins, permissions, hooks |
| Gemini settings | `tools/settings/gemini.json.tmpl` → `~/.gemini/settings.json` | Full adapter output |
| Codex settings | `tools/settings/codex.toml.tmpl` → `~/.codex/config.toml` | Full adapter output |
| Pi settings | `~/.pi/agent/settings.json` | User-owned; no full adapter |

**Model routing in workspace rules is guidance, not an assertion about your active
model.** Global Claude can use Opus while workspace examples describe a tiered
executor/advisor workflow. Likewise, hooks in the library are not automatically
installed as global Claude hooks. Plugins and project settings add their own layers.
Do not quote historical fixed token budgets as current measurements; use
`bash scripts/load-plan.sh` for the current workspace view.

## Full capability installation

```bash
bash scripts/install.sh --target=claude --dry-run
bash scripts/install.sh --target=gemini --dry-run
bash scripts/install.sh --target=codex --dry-run
# Omit --dry-run only after reviewing the generated configuration.
```

Full installs can replace CLI settings. Prefer `--instructions-only` when unifying
instructions. Do not use a full install merely to repair one setting or preserve a
user's existing model selection. `--target=all` links all four instruction entries
and runs the three existing full adapters.

Canonical library content lives under `tools/`: rules, agents, commands, hooks,
MCP definitions, and settings templates. Shared workspace skills have been removed
from the current working tree; provider/plugin skills are managed separately. Do
not assume historical `/debug`, `/research`, or `/tdd` workspace skills are installed.
Current workspace commands are `deep-review`, `healthcheck`, `init-project`, and
`load-plan`. See [`tools/README.md`](tools/README.md).

### Compatibility and safety

- **Gemini:** current settings use `model.name`, `ui.theme`, and `tools.sandbox`.
  Hook definitions use native event names and nested `hooks` arrays. Generated
  workspace hooks are **disabled by default** until their Gemini input/output
  contracts are tested; schema compatibility is not runtime parity.
- **Codex:** templates use `approval_policy = "on-request"` and
  `sandbox_mode = "workspace-write"`, not obsolete `approval_mode` / `sandbox` keys.
  Trust individual repositories, not the entire home directory.
- **Pi:** the default provider/model should match the configured model scope.
  A resumed session can legitimately use a different model or reasoning level.
- **Claude:** model and plugin choices are user preferences. Permission-warning
  suppression is not the same as a sandbox and should not be treated as one.

## Repair existing local settings

The targeted migration preserves unrelated keys and models, backs up changed files
privately, detects concurrent edits, and rolls back writes on failure:

```bash
python3 scripts/repair-local-config.py          # preview; no writes
python3 scripts/repair-local-config.py --apply  # Python 3.11+
```

It migrates Gemini's schema, enables its tool sandbox, disables only migrated
legacy hooks, fixes an out-of-scope Pi default, restores Claude permission warnings,
and updates Codex approval/sandbox keys while removing blanket home trust.
It uses standard home-relative paths; `--home` supports isolated tests. For custom
CLI config directories, review and migrate those settings separately.
Backups live under `~/.local/state/ai-cli-workspace/config-repair/` and preserve
original relative paths. Restore individual files from the printed backup directory
with `cp -p` while the corresponding CLI is stopped.

No login credentials are inspected or modified. CLI parsing checks do not prove
provider authentication, hook execution, or sandbox enforcement.

## Verification and working-tree discipline

```bash
python3 -m unittest discover -s tests -v
bash scripts/healthcheck.sh
```

Check `git status` before installation. Existing uncommitted edits and deletions are
user work, not configuration corruption: review them separately, never reset or
bulk-commit them to obtain a clean status. Stage only the intended repair files.

## License

MIT License
