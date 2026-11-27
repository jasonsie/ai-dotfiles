#!/usr/bin/env bash
# scripts/healthcheck.sh — verify this Mac matches the workspace (read-only).
#
# Checks live state through each CLI where possible, not generated files:
#   - install.sh --dry-run reports zero pending changes: every instruction, skill, hook
#     and command link is in place, and every managed setting is applied
#   - each install step's own checks (lib/install/run.py check): shared MCP servers are listed by
#     each CLI's own `mcp list`, the daily-log pass's LaunchAgent is loaded (when claude is installed)
#   - ~/.local/bin is on PATH, so `ai-dotfiles` runs from any folder
#   - `ai-dotfiles statusline`, the status line Claude Code and Antigravity run, renders a line
#   - repo sources contain no machine-specific paths; unit tests pass
#
# Run in a linked worktree, the live state is measured against the main checkout, which the
# live setup runs from (installer.live_root); the sources and tests checked stay this checkout's.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
LIVE="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import installer; print(installer.live_root(sys.argv[2]))' \
  "$ROOT/lib/install" "$ROOT" 2>/dev/null)"
[ -f "$LIVE/scripts/install.sh" ] || LIVE="$ROOT"
FAILS=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
detail() { sed 's/^/          /'; }

echo "-- pending changes (install.sh --dry-run)"
[ "$LIVE" = "$ROOT" ] || printf '  info  a linked worktree: measured against the main checkout, %s\n' "$LIVE"
if DRY="$(bash "$LIVE/scripts/install.sh" --dry-run 2>&1)"; then
  if printf '%s\n' "$DRY" | grep -qE '(^|: )[1-9][0-9]* changes'; then
    fail "pending changes (apply them: ai-dotfiles):"
    printf '%s\n' "$DRY" | grep -E '^Would ' | detail
  else
    pass "no pending changes"
  fi
else
  fail "install.sh --dry-run failed:"
  printf '%s\n' "$DRY" | tail -n 3 | detail
fi
# Model choices made in a CLI itself are kept on purpose; report them, never fail.
printf '%s\n' "$DRY" | sed -n 's/^Local choice kept: /  info  local choice kept: /p'
printf '%s\n' "$DRY" | sed -n 's/^Warning: /  info  /p'

# Each step's own checks (mcp: each CLI lists the shared servers; launchd: the daily-log pass is loaded).
STEP_CHECKS="$("$PYTHON" "$ROOT/lib/install/run.py" check 2>&1)"; STEP_STATUS=$?
printf '%s\n' "$STEP_CHECKS"
FAILS=$((FAILS + $(printf '%s\n' "$STEP_CHECKS" | grep -c '^  FAIL ')))
if [ "$STEP_STATUS" -ne 0 ] && ! printf '%s\n' "$STEP_CHECKS" | grep -q '^  FAIL '; then
  fail "the step checks did not run (exit $STEP_STATUS; run: $PYTHON lib/install/run.py check)"
fi

echo "-- command"
case ":$PATH:" in
  *":$HOME/.local/bin:"*|*":$HOME/.local/bin/:"*) pass "$HOME/.local/bin on PATH" ;;
  *) fail "$HOME/.local/bin is not on PATH; ai-dotfiles only runs by its full path" ;;
esac

echo "-- status line (ai-dotfiles statusline, run by Claude Code and Antigravity)"
if OUT="$(printf '{"model":{"display_name":"check"},"version":"0"}' | "$PYTHON" "$ROOT/scripts/statusline.py" 2>&1)" && [ -n "$OUT" ]; then
  pass "statusline renders a line"
else
  fail "statusline failed: $OUT"
fi

echo "-- portability"
HITS="$(grep -rlIE --exclude=healthcheck.sh --exclude-dir=__pycache__ --exclude-dir=tests \
  '/Users/[A-Za-z]|/opt/homebrew|/usr/local/Cellar' "$ROOT/config" "$ROOT/lib" "$ROOT/scripts" 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  fail "machine-specific paths in: $(printf '%s' "$HITS" | tr '\n' ' ')"
else
  pass "no machine-specific paths in config/, lib/ or scripts/"
fi

echo "-- tests"
if (cd "$ROOT" && "$PYTHON" -m unittest discover -s scripts/tests >/dev/null 2>&1); then pass "unit tests"; else fail "unit tests (run: $PYTHON -m unittest discover -s scripts/tests)"; fi

echo
if [ "$FAILS" -eq 0 ]; then echo "healthy"; else echo "$FAILS check(s) failed"; fi
exit $((FAILS > 0))
