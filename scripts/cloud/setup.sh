#!/usr/bin/env bash
# scripts/cloud/setup.sh — set up a Claude Code cloud session's VM the way ai-dotfiles sets up a Mac.
#
# A cloud environment's setup script (scripts/cloud/environment.sh, pasted on claude.ai) clones this
# repo to /opt/ai-dotfiles and runs this file as root, before Claude Code starts. The result is
# cached as a filesystem snapshot for about a week. Steps:
#   install  install.sh --cloud: ~/.claude/CLAUDE.md, the settings keys, context7, the skills a
#            cloud session can run, small-commits' hook (docs/how-it-works.md, Cloud sessions)
#   command  ai-dotfiles linked into $AI_DOTFILES_BIN (/usr/local/bin, on every PATH)
#   clone    each plugin config/plugins.json gives Claude, at its release tag, into $AI_PLUGINS_DIR
#            (/opt/ai-plugins)
#   plugin   each plugin's own cloud/setup.sh, when it ships one, with every pin as <NAME>_REF
#            (zkfy's installs web-clipper's CLI, Playwright Chromium, yt-dlp)
# Claude Code loads those plugins only through CLAUDE_CODE_PLUGIN_DIRS, which the report's last
# line gives: set it on the cloud environment once.
#
# It never fails the session: each step writes "ok" or "FAIL" to the report ($AI_DOTFILES_REPORT,
# /opt/ai-dotfiles-setup.txt) and its output to the log beside it, and the exit is 0.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLUGINS="${AI_PLUGINS_DIR:-/opt/ai-plugins}"
BIN="${AI_DOTFILES_BIN:-/usr/local/bin}"
REPORT="${AI_DOTFILES_REPORT:-/opt/ai-dotfiles-setup.txt}"
LOG="${REPORT%.txt}.log"
PYTHON="${PYTHON:-python3}"
export PYTHON

mkdir -p "$(dirname "$REPORT")" "$PLUGINS" "$BIN"
: >"$REPORT"
: >"$LOG"

report() { printf '%-4s %-10s %s\n' "$1" "$2" "$3" >>"$REPORT"; }

# step <name> <what> <command...>: run it, log its output, report the outcome.
step() {
  local name=$1 what=$2 status=0
  shift 2
  echo "== $name $what" >>"$LOG"
  "$@" >>"$LOG" 2>&1 || status=$?
  if [ "$status" = 0 ]; then report ok "$name" "$what"; else report FAIL "$name" "$what (exit $status; see $LOG)"; fi
  return "$status"
}

# name, source and release tag of each plugin config/plugins.json gives Claude, one per line.
pins() {
  "$PYTHON" - "$ROOT/config/plugins.json" <<'PY'
import json
import sys
for name, plugin in json.load(open(sys.argv[1]))['plugins'].items():
    if 'claude' in plugin['targets']:
        print(name, plugin['source'], f"{name}--v{plugin['version']}")
PY
}

step install "install.sh --cloud" bash "$ROOT/scripts/install.sh" --cloud
step command "$BIN/ai-dotfiles" ln -sfn "$ROOT/scripts/ai-dotfiles" "$BIN/ai-dotfiles"

DIRS=()
CLONED=()
while read -r name source tag; do
  ref="$(printf '%s' "$name" | tr '[:lower:]-' '[:upper:]_')_REF"
  printf -v "$ref" '%s' "$tag"
  export "${ref?}"
  DIRS+=("$PLUGINS/$name")
  rm -rf "${PLUGINS:?}/$name"
  if step clone "$source@$tag" git clone --quiet --depth 1 --branch "$tag" "https://github.com/$source" "$PLUGINS/$name"; then
    CLONED+=("$name")
  fi
done < <(pins)

# After every clone, so each plugin's setup sees every pin; from a copy, since one may replace its folder.
for name in ${CLONED[@]+"${CLONED[@]}"}; do
  if [ -f "$PLUGINS/$name/cloud/setup.sh" ]; then
    copy="$(mktemp)"
    cp "$PLUGINS/$name/cloud/setup.sh" "$copy"
    step plugin "$name/cloud/setup.sh" bash "$copy"
    rm -f "$copy"
  fi
done

report info env "CLAUDE_CODE_PLUGIN_DIRS=$(IFS=:; printf '%s' "${DIRS[*]-}")"
exit 0
