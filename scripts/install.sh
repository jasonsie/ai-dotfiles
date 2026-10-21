#!/usr/bin/env bash
# scripts/install.sh — apply the workspace's global CLI config on this Mac.
#
# Usage:
#   bash scripts/install.sh [--dry-run] [--update] [--target=all|claude|codex|pi|agy]
#                           [--instructions-only] [--replace-instructions]
#   Writes by default; --dry-run previews and writes nothing. --update first pulls this
#   repo (fast-forward only; clean tree on main), then installs. After the first run,
#   `ai-dotfiles` runs this from any folder.
#
# Steps (each is idempotent, dry-run aware, and backs up before writing):
#   1. instructions  tools/instructions/AGENTS.md → each CLI's global entry (symlink)
#   2. settings      tools/settings/managed.json  → merged into live settings (only those keys)
#   3. mcp           tools/mcp/servers.json       → native `<cli> mcp add` when missing
#   4. knowledge     zkfy vault launcher + query skill (Claude, Codex, Pi, AGY); skipped if
#                    ZKFY_DIR/ZKFY_VAULT are unset and no binding exists yet
#   5. skills        skills/<name>/                → linked into each CLI's skill folder
#   6. hooks         skills/learn/hooks/           → merged into each CLI's hook file (Pi: extension link)
#   7. command       scripts/ai-dotfiles           → ~/.local/bin/ai-dotfiles (link)
#
# Requires Python 3.11+ (macOS /usr/bin/python3 is older; use Homebrew/pyenv).
# Undo with scripts/uninstall.sh. See docs/adr/0005-global-config-single-source.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

TARGET="all"
DRY_RUN=0
UPDATE=0
INSTRUCTIONS_ONLY=0
REPLACE_INSTRUCTIONS=0
PASS=()

usage() { sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --target=*) TARGET="${arg#--target=}" ;;
    --dry-run) DRY_RUN=1 ;;
    --update) UPDATE=1; continue ;;
    --instructions-only) INSTRUCTIONS_ONLY=1 ;;
    --replace-instructions) REPLACE_INSTRUCTIONS=1 ;;
    --help|-h) usage; exit 0 ;;
    *) printf '[ERR] Unknown argument: %s\n' "$arg" >&2; usage >&2; exit 1 ;;
  esac
  PASS+=("$arg")
done

case "$TARGET" in
  all|claude|codex|pi|agy) ;;
  *) printf '[ERR] Invalid target: %s\n' "$TARGET" >&2; exit 1 ;;
esac

if [ "$UPDATE" = "1" ]; then
  echo "== update"
  BRANCH="$(git -C "$ROOT" symbolic-ref --quiet --short HEAD || true)"
  if [ "$BRANCH" != "main" ]; then
    printf '[ERR] update pulls main only; this checkout is on %s. Switch to main first.\n' "${BRANCH:-a detached HEAD}" >&2
    exit 1
  fi
  if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    printf '[ERR] update needs a clean tree; commit or stash your changes first:\n' >&2
    git -C "$ROOT" status --short >&2
    exit 1
  fi
  BEFORE="$(git -C "$ROOT" rev-parse HEAD)"
  git -C "$ROOT" fetch --quiet origin main
  if [ "$BEFORE" = "$(git -C "$ROOT" rev-parse FETCH_HEAD)" ]; then
    echo "Already up to date."
  elif [ "$DRY_RUN" = "1" ]; then
    echo "Would pull:"
    git -C "$ROOT" log --oneline "$BEFORE..FETCH_HEAD"
  else
    git -C "$ROOT" merge --ff-only --quiet FETCH_HEAD
    echo "Pulled:"
    git -C "$ROOT" log --oneline "$BEFORE..HEAD"
    # Bash reads a script while running it; continue with the freshly pulled copy.
    exec bash "$SCRIPT_DIR/install.sh" ${PASS[@]+"${PASS[@]}"}
  fi
fi

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  printf '[ERR] Python 3.11+ required (found: %s). Install one (brew install python) or set PYTHON=/path/to/python3.\n' \
    "$("$PYTHON" --version 2>&1 || echo none)" >&2
  exit 1
fi

DRY=()
[ "$DRY_RUN" = "1" ] && DRY=(--dry-run)

echo "== instructions"
INSTRUCTION_ARGS=(--target "$TARGET" ${DRY[@]+"${DRY[@]}"})
[ "$REPLACE_INSTRUCTIONS" = "1" ] && INSTRUCTION_ARGS+=(--replace-existing)
"$PYTHON" "$SCRIPT_DIR/install-global-instructions.py" "${INSTRUCTION_ARGS[@]}"
[ "$INSTRUCTIONS_ONLY" = "1" ] && exit 0

echo "== settings"
"$PYTHON" "$SCRIPT_DIR/apply-settings.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== mcp"
"$PYTHON" "$SCRIPT_DIR/apply-mcp.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== knowledge"
case "$TARGET" in
  all) KNOWLEDGE_TARGET=all ;;
  claude) KNOWLEDGE_TARGET=claude ;;
  codex|pi) KNOWLEDGE_TARGET=agents ;;
  agy) KNOWLEDGE_TARGET=agy ;;
  *) KNOWLEDGE_TARGET="" ;;
esac
if [ -z "$KNOWLEDGE_TARGET" ]; then
  echo "knowledge: not used by $TARGET"
elif [ -n "${ZKFY_DIR:-}" ] || [ -f "${HOME}/.config/zkfy/knowledge.json" ]; then
  "$PYTHON" "$SCRIPT_DIR/install-vault-knowledge.py" --target "$KNOWLEDGE_TARGET" ${DRY[@]+"${DRY[@]}"}
else
  echo "knowledge: skipped (set ZKFY_DIR and ZKFY_VAULT to enable vault retrieval)"
fi

echo "== skills"
# Same folders as the knowledge step: Codex and Pi share ~/.agents/skills.
"$PYTHON" "$SCRIPT_DIR/install-skills.py" --target "$KNOWLEDGE_TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== hooks"
"$PYTHON" "$SCRIPT_DIR/install-hooks.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== command"
"$PYTHON" "$SCRIPT_DIR/install-command.py" ${DRY[@]+"${DRY[@]}"}

[ "$DRY_RUN" = "1" ] && echo "Preview only: nothing written. Run again without --dry-run to write." || echo "Done. Verify: ai-dotfiles check"
