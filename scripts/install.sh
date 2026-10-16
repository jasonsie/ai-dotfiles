#!/usr/bin/env bash
# scripts/install.sh — apply the workspace's global CLI config on this Mac.
#
# Usage:
#   bash scripts/install.sh [--target=all|claude|codex|gemini|pi] [--dry-run]
#                           [--instructions-only] [--replace-instructions]
#
# Steps (each is idempotent, dry-run aware, and backs up before writing):
#   1. instructions  tools/instructions/AGENTS.md → each CLI's global entry (symlink)
#   2. settings      tools/settings/managed.json  → merged into live settings (only those keys)
#   3. mcp           tools/mcp/servers.json       → native `<cli> mcp add` when missing
#   4. knowledge     zkfy vault launcher + query skill (Claude, Pi); skipped if
#                    ZKFY_DIR/ZKFY_VAULT are unset and no binding exists yet
#
# Requires Python 3.11+ (macOS /usr/bin/python3 is older; use Homebrew/pyenv).
# See docs/adr/0005-global-config-single-source.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET="all"
DRY_RUN=0
INSTRUCTIONS_ONLY=0
REPLACE_INSTRUCTIONS=0

usage() { sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --target=*) TARGET="${arg#--target=}" ;;
    --dry-run) DRY_RUN=1 ;;
    --instructions-only) INSTRUCTIONS_ONLY=1 ;;
    --replace-instructions) REPLACE_INSTRUCTIONS=1 ;;
    --help|-h) usage; exit 0 ;;
    *) printf '[ERR] Unknown argument: %s\n' "$arg" >&2; usage >&2; exit 1 ;;
  esac
done

case "$TARGET" in
  all|claude|codex|gemini|pi) ;;
  *) printf '[ERR] Invalid target: %s\n' "$TARGET" >&2; exit 1 ;;
esac

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  printf '[ERR] Python 3.11+ required (found: %s). Install one (brew install python) or set PYTHON=/path/to/python3.\n' \
    "$("$PYTHON" --version 2>&1 || echo none)" >&2
  exit 1
fi

APPLY=()
[ "$DRY_RUN" = "1" ] || APPLY=(--apply)

echo "== instructions"
INSTRUCTION_ARGS=(--target "$TARGET" ${APPLY[@]+"${APPLY[@]}"})
[ "$REPLACE_INSTRUCTIONS" = "1" ] && INSTRUCTION_ARGS+=(--replace-existing)
"$PYTHON" "$SCRIPT_DIR/install-global-instructions.py" "${INSTRUCTION_ARGS[@]}"
[ "$INSTRUCTIONS_ONLY" = "1" ] && exit 0

echo "== settings"
"$PYTHON" "$SCRIPT_DIR/apply-settings.py" --target "$TARGET" ${APPLY[@]+"${APPLY[@]}"}

echo "== mcp"
"$PYTHON" "$SCRIPT_DIR/apply-mcp.py" --target "$TARGET" ${APPLY[@]+"${APPLY[@]}"}

echo "== knowledge"
case "$TARGET" in
  all) KNOWLEDGE_TARGET=both ;;
  claude|pi) KNOWLEDGE_TARGET="$TARGET" ;;
  *) KNOWLEDGE_TARGET="" ;;
esac
if [ -z "$KNOWLEDGE_TARGET" ]; then
  echo "knowledge: not used by $TARGET"
elif [ -n "${ZKFY_DIR:-}" ] || [ -f "${HOME}/.config/zkfy/knowledge.json" ]; then
  "$PYTHON" "$SCRIPT_DIR/install-vault-knowledge.py" --target "$KNOWLEDGE_TARGET" ${APPLY[@]+"${APPLY[@]}"}
else
  echo "knowledge: skipped (set ZKFY_DIR and ZKFY_VAULT to enable vault retrieval)"
fi

[ "$DRY_RUN" = "1" ] && echo "Dry run: nothing written." || echo "Done. Verify: bash scripts/healthcheck.sh"
