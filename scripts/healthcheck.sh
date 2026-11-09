#!/usr/bin/env bash
# scripts/healthcheck.sh — verify this Mac matches the workspace (read-only).
#
# Checks live state through each CLI where possible, not generated files:
#   - install.sh --dry-run reports zero pending changes: every instruction, skill, hook
#     and command link is in place, and every managed setting is applied
#   - shared MCP servers are listed by each CLI's own `mcp list`
#   - ~/.local/bin is on PATH, so `ai-dotfiles` runs from any folder
#   - `ai-dotfiles statusline`, the status line Claude Code and Antigravity run, renders a line
#   - the daily-log pass's LaunchAgent is loaded (when claude is installed)
#   - repo sources contain no machine-specific paths; unit tests pass
#
# Run in a linked worktree, the live state is measured against the main checkout, which the
# live setup runs from (installer.live_root); the sources and tests checked stay this checkout's.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
LIVE="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import installer; print(installer.live_root(sys.argv[2]))' \
  "$ROOT/scripts/install" "$ROOT" 2>/dev/null)"
[ -f "$LIVE/scripts/install.sh" ] || LIVE="$ROOT"
FAILS=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
skip() { printf '  skip  %s\n' "$1"; }
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

echo "-- mcp (each CLI switched on in config/ai-clis.json; Antigravity has no list, so its file is read)"
SERVERS="$("$PYTHON" -c 'import json,sys; print(" ".join(s["name"] for s in json.load(open(sys.argv[1]))["servers"]))' "$LIVE/config/mcp-servers.json")"
for entry in $("$PYTHON" -c 'import json,sys; c=json.load(open(sys.argv[1]))["clis"]; print(" ".join(k + "=" + v["mcp"] for k, v in c.items() if v["on"]))' "$LIVE/config/ai-clis.json"); do
  cli="${entry%%=*}"; file="$HOME/${entry#*=\~/}"
  for name in $SERVERS; do
    if [ "$cli" = agy ]; then
      if [ ! -f "$file" ]; then
        skip "agy not set up"
      elif "$PYTHON" -c 'import json,sys; t=open(sys.argv[1]).read(); sys.exit(sys.argv[2] not in (json.loads(t) if t.strip() else {}).get("mcpServers", {}))' "$file" "$name"; then
        pass "agy: $name (in $(basename "$file"))"
      else
        fail "agy: $name not in $file"
      fi
    elif ! command -v "$cli" >/dev/null 2>&1; then
      skip "$cli not on PATH"
    else
      # A server disabled for the current folder is still configured; count it as present.
      line="$("$cli" mcp list 2>&1 | grep -m1 "$name" || true)"
      case "$line" in
        "") fail "$cli: $name not listed" ;;
        *Disabled*) pass "$cli: $name (configured; disabled in this untrusted folder)" ;;
        *) pass "$cli: $name" ;;
      esac
    fi
  done
done

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

echo "-- launchd (the daily-log pass, 04:00 each day)"
PLIST="$HOME/Library/LaunchAgents/com.ai-dotfiles.daily-log-day.plist"
if ! command -v claude >/dev/null 2>&1; then
  skip "claude not on PATH: nothing to schedule"
elif [ ! -f "$PLIST" ]; then
  fail "not scheduled: $PLIST missing (run: ai-dotfiles)"
elif launchctl print "gui/$(id -u)/com.ai-dotfiles.daily-log-day" >/dev/null 2>&1; then
  pass "com.ai-dotfiles.daily-log-day loaded"
else
  fail "com.ai-dotfiles.daily-log-day not loaded (run: ai-dotfiles)"
fi

echo "-- portability"
HITS="$(grep -rlIE --exclude=healthcheck.sh --exclude-dir=__pycache__ --exclude-dir=tests \
  '/Users/[A-Za-z]|/opt/homebrew|/usr/local/Cellar' "$ROOT/config" "$ROOT/scripts" 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  fail "machine-specific paths in: $(printf '%s' "$HITS" | tr '\n' ' ')"
else
  pass "no machine-specific paths in config/ or scripts/"
fi

echo "-- tests"
if (cd "$ROOT" && "$PYTHON" -m unittest discover -s scripts/tests >/dev/null 2>&1); then pass "unit tests"; else fail "unit tests (run: $PYTHON -m unittest discover -s scripts/tests)"; fi

echo
if [ "$FAILS" -eq 0 ]; then echo "healthy"; else echo "$FAILS check(s) failed"; fi
exit $((FAILS > 0))
