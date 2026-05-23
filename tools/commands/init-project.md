---
name: init-project
description: Bootstrap a project-local .claude/CLAUDE.md by selecting dimension profiles (frontend, backend, etc.) from ai-cli-workspace.
---

# Init Project — Stage 2 bootstrap

Run the workspace bootstrap script to write a project-local
`.claude/CLAUDE.md` based on which dimensions apply (frontend, backend,
data-analysis, etc.). The user-global rules from Stage 1 install already
load for every session — this command only adds a strict additive layer
on top.

## How to invoke

If `gum` is installed, the script uses `gum choose --no-limit` for a
multi-select picker. Otherwise it falls back to per-profile `y/N`
prompts. For non-interactive use, pass `--profile=<csv>`.

```bash
WS="$(cat ~/.ai-cli-workspace-path)"

# Interactive
bash "$WS/scripts/init-project.sh"

# Non-interactive
bash "$WS/scripts/init-project.sh" --profile=frontend
bash "$WS/scripts/init-project.sh" --profile=frontend,backend

# Preview without writing
bash "$WS/scripts/init-project.sh" --profile=frontend --dry-run
```

The path is pinned at install time to `~/.ai-cli-workspace-path` by
`scripts/install.sh`. If that file is missing, Stage 1 hasn't been run
yet — run `bash scripts/install.sh` from the workspace checkout first.

## Semantics

- Writes only `<project>/.claude/CLAUDE.md` plus a `.workspace-managed`
  marker. Never touches `~/.claude/` (that's Stage 1's territory).
- Re-running refreshes the generated sections; anything you wrote below
  the `<!-- USER-CONTENT-BELOW -->` sentinel is preserved verbatim.
- If `CLAUDE.md` already exists *without* the marker, the script refuses
  to overwrite — delete it first if you want `/init-project` to manage it.

## Profile schema

Profiles live in `tools/profiles/<dimension>.yaml`. Each profile lists
the skills it surfaces. Selecting multiple dimensions composes them by
union of skills. Add new dimensions by creating a new YAML file in the
same shape.
