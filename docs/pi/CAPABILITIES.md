# Pi — knowledge adapter scope

This is a deliberately narrow capability catalog, not a claim of full workspace parity.

| Capability | Native surface | Delivery |
|---|---|---|
| Resident knowledge trigger | `~/.pi/agent/AGENTS.md` (or configured agent directory) | Symlink to the shared `tools/instructions/AGENTS.md` (its retrieval section) |
| On-demand query procedure | global `skills/<name>/SKILL.md` | Link to the same zkfy `query` definition used by Claude, in `~/.agents/skills` (read natively by Pi) |
| Scoped retrieval | shell tool | `~/.local/bin/vault-knowledge`, explicit machine-local vault binding |
| MCP | none (by design) | Not emulated; see ADR-0005 Q2/Q8 |
| Manual skill invocation | `/skill:query` | Pi native discovery |

Source: installed Pi 0.85.1 README Context Files and `docs/skills.md` (read during implementation). Pi loads skill descriptions at startup and full skill text on demand; models do not always auto-load a skill, so fresh-session runtime tests remain necessary.

`scripts/install.sh` links the shared instructions; `scripts/install-vault-knowledge.py --target agents` links the zkfy `query` skill into `~/.agents/skills` (read by Pi and Codex) and the launcher (paths from `--zkfy/--vault`, `ZKFY_DIR/ZKFY_VAULT`, or the existing binding). It never edits instruction files; its ownership receipt supports exact rollback with `--uninstall`. Fresh-session runtime tests remain necessary: models do not always auto-load a skill.
