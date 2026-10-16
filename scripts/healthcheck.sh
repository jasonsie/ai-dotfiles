#!/usr/bin/env bash
# scripts/healthcheck.sh — verify this Mac matches the workspace (read-only).
#
# Checks live state through each CLI where possible, not generated files:
#   - global instruction entries link to tools/instructions/AGENTS.md
#   - install.sh --dry-run reports zero pending changes
#   - shared MCP servers are listed by each CLI's own `mcp list`
#   - vault launcher resolves (when bound)
#   - repo sources contain no machine-specific paths; unit tests pass

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
FAILS=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
skip() { printf '  skip  %s\n' "$1"; }

echo "-- instructions"
SOURCE="$ROOT/tools/instructions/AGENTS.md"
for entry in ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.gemini/GEMINI.md "${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/AGENTS.md"; do
  if [ ! -d "$(dirname "$entry")" ]; then
    skip "$entry (CLI not set up)"
  elif [ "$(cd "$(dirname "$entry")" && "$PYTHON" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$entry")" = "$SOURCE" ]; then
    pass "$entry"
  else
    fail "$entry does not link to $SOURCE"
  fi
done

echo "-- pending changes (install.sh --dry-run)"
DRY="$(bash "$ROOT/scripts/install.sh" --dry-run 2>&1)" || fail "install.sh --dry-run exited non-zero"
PENDING="$(printf '%s\n' "$DRY" | grep -E '(^|: )[1-9][0-9]* changes' || true)"
if [ -z "$PENDING" ]; then pass "no pending changes"; else fail "pending: $(printf '%s' "$PENDING" | tr '\n' ';')"; fi
# Model choices made in a CLI itself are kept on purpose; report them, never fail.
printf '%s\n' "$DRY" | sed -n 's/^Local choice kept: /  info  local choice kept: /p'

echo "-- mcp (native list)"
for name in $("$PYTHON" -c 'import json,sys; print(" ".join(s["name"] for s in json.load(open(sys.argv[1]))["servers"]))' "$ROOT/tools/mcp/servers.json"); do
  for cli in claude codex; do
    if ! command -v "$cli" >/dev/null 2>&1; then skip "$cli not on PATH"; continue; fi
    # A server disabled for the current folder is still configured; count it as present.
    line="$("$cli" mcp list 2>&1 | grep -m1 "$name" || true)"
    case "$line" in
      "") fail "$cli: $name not listed" ;;
      *Disabled*) pass "$cli: $name (configured; disabled in this untrusted folder)" ;;
      *) pass "$cli: $name" ;;
    esac
  done
done

echo "-- knowledge"
if [ -f ~/.config/zkfy/knowledge.json ]; then
  if [ -e ~/.local/bin/vault-knowledge ]; then pass "vault-knowledge launcher resolves"; else fail "vault-knowledge launcher missing or dangling"; fi
else
  skip "no zkfy binding on this machine"
fi

echo "-- portability"
HITS="$(grep -rlIE --exclude=healthcheck.sh --exclude-dir=__pycache__ \
  '/Users/[A-Za-z]|/opt/homebrew|/usr/local/Cellar' "$ROOT/tools" "$ROOT/scripts" 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  fail "machine-specific paths in: $(printf '%s' "$HITS" | tr '\n' ' ')"
else
  pass "no machine-specific paths in tools/ or scripts/"
fi

echo "-- tests"
if (cd "$ROOT" && "$PYTHON" -m unittest discover -s tests >/dev/null 2>&1); then pass "unit tests"; else fail "unit tests (run: $PYTHON -m unittest discover -s tests)"; fi

echo
if [ "$FAILS" -eq 0 ]; then echo "healthy"; else echo "$FAILS check(s) failed"; fi
exit $((FAILS > 0))
