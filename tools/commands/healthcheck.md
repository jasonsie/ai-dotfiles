---
name: healthcheck
description: Validate workspace integrity (symlinks, settings, hook scripts, manifests)
---

# Healthcheck

Run `bash scripts/healthcheck.sh` and report results.

Validates:
- `tools/` directory structure intact
- All `.claude/` symlinks resolve to `tools/` targets
- Generated `~/.claude/settings.json`, `~/.gemini/settings.json`, `~/.codex/config.toml` parse cleanly
- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` exist and reference correct paths
- Hook scripts have valid syntax (`bash -n`) and executable bits
- `skills-lock.json` references resolve

If any check fails, surface the exact failing file/path and stop. Don't try to auto-fix — report and let the user decide.
