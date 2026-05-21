---
name: load-plan
description: Print the four-tier context-loading plan with token estimates for the current workspace
---

# Load Plan

Display the four-tier loading framework currently active for this workspace:

- 🔴 **Real-time** — SessionStart hook + CLAUDE.md body
- 🟡 **Auto** — rules @-imported from CLAUDE.md / AGENTS.md (always loaded)
- 🟢 **On-demand** — skills + commands (only on trigger words)
- ⚪ **Skip** — archives, reference docs (manual Read only)

For each tier, list the active files with rough token estimates (chars / 4). Surface anything unusually large (>2000 tokens in auto-load). Suggest deferring or pruning if total auto-load exceeds 5000 tokens.

If `scripts/load-plan.sh` exists, run it and display its output.
