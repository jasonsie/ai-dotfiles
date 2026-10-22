#!/usr/bin/env bash
# scripts/uninstall.sh — remove everything install.sh made that points into this repo.
#
# Usage:
#   bash scripts/uninstall.sh [--dry-run] [--target=all|<cli in config/ai-clis.json>]
#   Writes by default; --dry-run previews and writes nothing. Switches in ai-clis.json
#   do not matter here: every selected CLI is uninstalled.
#
# Steps, in reverse install order (each removes only what its installer created,
# backs up before writing, and rolls back on failure):
#   5. skills        links in the receipt: skills, and the ai-dotfiles command
#                    (that one with --target=all only)
#   4. knowledge     zkfy vault binding (--target=all only; receipt restores prior state)
#   3. mcp           left in place, listed: servers do not depend on this repo
#   2. settings      left in place, listed: managed keys hold no repo paths
#   1. instructions  links removed; the file from before the first install is restored
#
# Afterwards, deleting this repo breaks nothing. Reinstall with scripts/install.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET="all"
DRY_RUN=0

usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --target=*) TARGET="${arg#--target=}" ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) printf '[ERR] Unknown argument: %s\n' "$arg" >&2; usage >&2; exit 1 ;;
  esac
done

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  printf '[ERR] Python 3.11+ required (found: %s). Install one (brew install python) or set PYTHON=/path/to/python3.\n' \
    "$("$PYTHON" --version 2>&1 || echo none)" >&2
  exit 1
fi
"$PYTHON" "$SCRIPT_DIR/install/installer.py"   # checks config/ai-clis.json

DRY=()
[ "$DRY_RUN" = "1" ] && DRY=(--dry-run)

echo "== skills"
"$PYTHON" "$SCRIPT_DIR/install/skills.py" --uninstall --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== knowledge"
if [ "$TARGET" != "all" ]; then
  echo "knowledge: kept (one binding for every CLI; removed with --target=all)"
elif [ -f "${HOME}/.local/state/zkfy/integration.json" ]; then
  "$PYTHON" "$SCRIPT_DIR/install/knowledge.py" --uninstall ${DRY[@]+"${DRY[@]}"}
else
  echo "knowledge: nothing installed"
fi

echo "== mcp"
"$PYTHON" "$SCRIPT_DIR/install/mcp.py" --uninstall --target "$TARGET"

echo "== settings"
"$PYTHON" "$SCRIPT_DIR/install/settings.py" --uninstall --target "$TARGET"

echo "== instructions"
"$PYTHON" "$SCRIPT_DIR/install/instructions.py" --uninstall --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

[ "$DRY_RUN" = "1" ] && echo "Preview only: nothing written. Run again without --dry-run to remove." || echo "Done. Reinstall: bash scripts/install.sh"
