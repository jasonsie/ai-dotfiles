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
# Requires Python 3.11+ (macOS /usr/bin/python3 is older; use Homebrew/pyenv).
# The steps are listed once, in lib/install/steps.py; `install.sh --help` prints them. Undo with
# scripts/uninstall.sh. See docs/how-it-works.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

DRY_RUN=0
UPDATE=0
HELP=0
PASS=()

# Only what must be shell is read here: --update runs before the steps, and a freshly pulled
# copy of this script takes over. lib/install/run.py reads every other argument.
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --update) UPDATE=1; continue ;;
    --help|-h) HELP=1 ;;
  esac
  PASS+=("$arg")
done

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
[ "$HELP" = "1" ] && exec "$PYTHON" "$ROOT/lib/install/run.py" help
exec "$PYTHON" "$ROOT/lib/install/run.py" install ${PASS[@]+"${PASS[@]}"}
