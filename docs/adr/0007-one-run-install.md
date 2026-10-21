# One-run install, update and uninstall through one global command

Status: **Accepted** 2026-10-21. Amends [ADR-0006](0006-redesign-round-2.md) Q29.
Decided in the interview recorded in `docs/plans/install-cli.md`.

## Context

Installing took two runs (a preview, then `--apply`), there was no way to undo an install
except by hand, updating meant a manual `git pull` and a rerun, and the installer had to be
called by its path from the repo root.

## Decisions

| # | Decision |
|---|---|
| 1, 2 | Every installer writes by default and previews with `--dry-run`; `--apply` is removed. Backups, idempotency, refusal to overwrite foreign files, and rollback stay. |
| 3, 4 | One command, `ai-dotfiles` (`install`, `update`, `uninstall`, `check`), wraps the repo scripts. `install.sh` links it into `~/.local/bin` with a receipt; shell files are never edited. |
| 5 | `update` fast-forwards `main` on a clean tree, then runs the freshly pulled installer. It never stashes, merges, switches branches, upgrades the CLIs, or touches `upstream/`. |
| 6 | `uninstall` removes whatever points into the repo (instruction links, restoring the file from before the first install; skill links; learn hooks; vault binding; command link). Settings keys and MCP servers stay and are listed: they hold no repo paths and cannot be told apart from the user's own. |

## Consequences

- A mistyped plain run writes at once; `--dry-run` and the backups are the safety net.
- The healthcheck's pending-changes check uses `install.sh --dry-run`.
- Uninstall is not a full return to the pre-install state for settings and MCP servers.
