#!/usr/bin/env bash
# scripts/uninstall.sh — remove everything install.sh made that points into this repo.
#
# Usage:
#   bash scripts/uninstall.sh [--dry-run] [--target=all|<cli in config/ai-clis.json>]
#   Writes by default; --dry-run previews and writes nothing. Switches in ai-clis.json
#   do not matter here: every selected CLI is uninstalled.
#
# Afterwards, deleting this repo breaks nothing. Reinstall with scripts/install.sh.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  printf '[ERR] Python 3.11+ required (found: %s). Install one (brew install python) or set PYTHON=/path/to/python3.\n' \
    "$("$PYTHON" --version 2>&1 || echo none)" >&2
  exit 1
fi
for arg in "$@"; do
  case "$arg" in --help|-h) exec "$PYTHON" "$ROOT/lib/install/run.py" help uninstall ;; esac
done
exec "$PYTHON" "$ROOT/lib/install/run.py" uninstall "$@"
