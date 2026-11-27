#!/usr/bin/env bash
# scripts/install.sh — apply the workspace's global CLI config on this Mac.
#
# Usage:
#   bash scripts/install.sh [--dry-run] [--update] [--target=all|<cli>]
#                           [--instructions-only] [--replace-instructions] [--cloud]
#   Writes by default; --dry-run previews and writes nothing. --update first pulls this
#   repo (fast-forward only; clean tree on main), then installs. config/ai-clis.json says
#   which CLIs are on: a run sets those up and takes this repo's links and hooks out of the
#   ones switched off; --target=<cli> limits a run to one CLI listed there. --cloud is a
#   Claude Code cloud session's VM (scripts/cloud/setup.sh runs it): Claude alone, the skills
#   config/cloud.json does not keep local, small-commits' hook; no plugins step, no launchd.
#
# Steps (each is idempotent, dry-run aware, and backs up before writing):
#   1. instructions  config/global-agents.md       → each CLI's global entry (symlink)
#   2. settings      config/cli-settings.json      → merged into live settings (only those keys)
#   3. mcp           config/mcp-servers.json       → native `<cli> mcp add` when missing
#   4. skills        skills/<name>/                → each CLI's skill folder (links); also
#                    scripts/ai-dotfiles and the daily-log command → ~/.local/bin, and
#                    Pi's hooks extension
#   5. plugins       config/plugins.json           → each CLI's own plugin manager, at the
#                    pinned release tag, each read back after
#   6. hooks         skills/*/feature.json        → one door entry per event in each CLI's
#                    hook file, the door's Python linked; retired hooks taken out
#   7. launchd       the daily-log pass            → ~/Library/LaunchAgents, 04:00 each day
#
# Requires Python 3.11+ (macOS /usr/bin/python3 is older; use Homebrew/pyenv).
# Steps live in lib/install/. Undo with scripts/uninstall.sh. See docs/how-it-works.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

TARGET="all"
DRY_RUN=0
UPDATE=0
INSTRUCTIONS_ONLY=0
REPLACE_INSTRUCTIONS=0
CLOUD=0
PASS=()

usage() { sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --target=*) TARGET="${arg#--target=}" ;;
    --dry-run) DRY_RUN=1 ;;
    --update) UPDATE=1; continue ;;
    --instructions-only) INSTRUCTIONS_ONLY=1 ;;
    --replace-instructions) REPLACE_INSTRUCTIONS=1 ;;
    --cloud) CLOUD=1 ;;
    --help|-h) usage; exit 0 ;;
    *) printf '[ERR] Unknown argument: %s\n' "$arg" >&2; usage >&2; exit 1 ;;
  esac
  PASS+=("$arg")
done
# A cloud session's VM runs Claude Code alone, and Claude reads ~/.claude only once it exists.
CLOUD_ARGS=()
if [ "$CLOUD" = "1" ]; then
  TARGET="claude"
  CLOUD_ARGS=(--cloud)
  [ "$DRY_RUN" = "1" ] || mkdir -p "$HOME/.claude"
fi

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
# Check config/ai-clis.json (and warn when a CLI folder override disagrees with it).
"$PYTHON" "$ROOT/lib/install/installer.py"

DRY=()
[ "$DRY_RUN" = "1" ] && DRY=(--dry-run)

echo "== instructions"
INSTRUCTION_ARGS=(--target "$TARGET" ${DRY[@]+"${DRY[@]}"})
[ "$REPLACE_INSTRUCTIONS" = "1" ] && INSTRUCTION_ARGS+=(--replace-existing)
"$PYTHON" "$ROOT/lib/install/instructions.py" "${INSTRUCTION_ARGS[@]}"
[ "$INSTRUCTIONS_ONLY" = "1" ] && exit 0

echo "== settings"
"$PYTHON" "$ROOT/lib/install/settings.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== mcp"
"$PYTHON" "$ROOT/lib/install/mcp.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"}

echo "== skills"
"$PYTHON" "$ROOT/lib/install/skills.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"} ${CLOUD_ARGS[@]+"${CLOUD_ARGS[@]}"}

echo "== plugins"
if [ "$CLOUD" = "1" ]; then
  echo "plugins: skipped in a cloud session (scripts/cloud/setup.sh clones them at their pins)"
else
  "$PYTHON" "$ROOT/lib/install/plugins.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"}
fi

echo "== hooks"
"$PYTHON" "$ROOT/lib/install/hooks.py" --target "$TARGET" ${DRY[@]+"${DRY[@]}"} ${CLOUD_ARGS[@]+"${CLOUD_ARGS[@]}"}

echo "== launchd"
if [ "$CLOUD" = "1" ]; then
  echo "launchd: skipped in a cloud session"
else
  "$PYTHON" "$ROOT/lib/install/launchd.py" ${DRY[@]+"${DRY[@]}"}
fi

[ "$DRY_RUN" = "1" ] && echo "Preview only: nothing written. Run again without --dry-run to write." || echo "Done. Verify: ai-dotfiles check"
