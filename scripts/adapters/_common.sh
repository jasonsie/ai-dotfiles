#!/usr/bin/env bash
# scripts/adapters/_common.sh — Shared helpers for workspace adapters
# Source this file; do NOT execute it directly.
#
# Usage in adapter scripts:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "${SCRIPT_DIR}/_common.sh"

set -euo pipefail

# ---------------------------------------------------------------------------
# Counters for final summary (only initialise if not already set)
# This prevents re-sourcing from resetting counts when adapters source _common.sh
# ---------------------------------------------------------------------------
: "${_SUMMARY_CREATED:=0}"
: "${_SUMMARY_UPDATED:=0}"
: "${_SUMMARY_UNCHANGED:=0}"
: "${_SUMMARY_SKIPPED:=0}"

# ---------------------------------------------------------------------------
# Colour codes (fallback to empty if not a tty)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  _CYAN='\033[0;36m'
  _YELLOW='\033[0;33m'
  _RED='\033[0;31m'
  _GREEN='\033[0;32m'
  _RESET='\033[0m'
else
  _CYAN='' _YELLOW='' _RED='' _GREEN='' _RESET=''
fi

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_info() { printf "${_CYAN}[INFO]${_RESET} %s\n" "$*"; }
log_warn() { printf "${_YELLOW}[WARN]${_RESET} %s\n" "$*"; }
log_ok()   { printf "${_GREEN}[OK]${_RESET}   %s\n" "$*"; }
log_err()  {
  printf "${_RED}[ERR]${_RESET}  %s\n" "$*" >&2
  if [ "${ALLOW_ERROR:-0}" != "1" ]; then
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Dry-run check
# ---------------------------------------------------------------------------
is_dry_run() {
  [ "${DRY_RUN:-0}" = "1" ]
}

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log_err "Required command not found: ${cmd}"
  fi
}

# ---------------------------------------------------------------------------
# ensure_dir <path>
# ---------------------------------------------------------------------------
ensure_dir() {
  local path
  path="$(eval echo "$1")"   # expand ~ in path
  if [ -d "$path" ]; then
    return 0
  fi
  if is_dry_run; then
    log_info "[dry-run] would create directory: ${path}"
    return 0
  fi
  mkdir -p "$path"
  log_ok "Created directory: ${path}"
}

# ---------------------------------------------------------------------------
# ensure_symlink <target> <link>
# Creates a symlink at <link> pointing to <target>.
# If <link> already points to <target>, does nothing.
# If <link> points elsewhere, updates it.
# ---------------------------------------------------------------------------
ensure_symlink() {
  local target="$1"
  local link
  link="$(eval echo "$2")"   # expand ~

  if [ -L "$link" ]; then
    local current
    current="$(readlink "$link")"
    if [ "$current" = "$target" ]; then
      log_info "Symlink unchanged: ${link} -> ${target}"
      summary_track unchanged
      return 0
    fi
    # Points elsewhere — update
    if is_dry_run; then
      log_info "[dry-run] would update symlink: ${link} -> ${target} (was: ${current})"
      summary_track updated
      return 0
    fi
    rm "$link"
    ln -s "$target" "$link"
    log_ok "Updated symlink: ${link} -> ${target}"
    summary_track updated
  elif [ -e "$link" ]; then
    log_warn "Path exists but is not a symlink, skipping: ${link}"
    summary_track skipped
  else
    if is_dry_run; then
      log_info "[dry-run] would create symlink: ${link} -> ${target}"
      summary_track created
      return 0
    fi
    # Ensure parent directory exists
    local link_dir
    link_dir="$(dirname "$link")"
    mkdir -p "$link_dir"
    ln -s "$target" "$link"
    log_ok "Created symlink: ${link} -> ${target}"
    summary_track created
  fi
}

# ---------------------------------------------------------------------------
# write_if_changed <dest> <content>
# Writes content (passed as a string) to dest only if it differs.
# Always returns 0 (safe to call under set -e).
# ---------------------------------------------------------------------------
write_if_changed() {
  local dest="$1"
  local content="$2"

  local expanded_dest
  expanded_dest="$(eval echo "$dest")"

  if [ -f "$expanded_dest" ]; then
    local existing
    existing="$(cat "$expanded_dest")"
    if [ "$existing" = "$content" ]; then
      log_info "Unchanged: ${expanded_dest}"
      summary_track unchanged
      return 0
    fi
    if is_dry_run; then
      log_info "[dry-run] would update: ${expanded_dest}"
      summary_track updated
      return 0
    fi
    printf '%s\n' "$content" > "$expanded_dest"
    log_ok "Updated: ${expanded_dest}"
    summary_track updated
  else
    if is_dry_run; then
      log_info "[dry-run] would create: ${expanded_dest}"
      summary_track created
      return 0
    fi
    local dest_dir
    dest_dir="$(dirname "$expanded_dest")"
    mkdir -p "$dest_dir"
    printf '%s\n' "$content" > "$expanded_dest"
    log_ok "Created: ${expanded_dest}"
    summary_track created
  fi
  return 0
}

# ---------------------------------------------------------------------------
# render_template <tmpl> <dest> <key1> <val1> [<key2> <val2> ...]
# Simple {{KEY}} substitution; writes dest if different.
# For JSON files with structured placeholders, prefer the Python-based helpers
# in claude.sh/gemini.sh which bypass this function entirely.
# ---------------------------------------------------------------------------
render_template() {
  local tmpl="$1"
  local dest="$2"
  shift 2

  if [ ! -f "$tmpl" ]; then
    log_err "Template not found: ${tmpl}"
    return 1
  fi

  local content
  content="$(cat "$tmpl")"

  # Substitute each key=value pair
  while [ $# -ge 2 ]; do
    local key="$1"
    local val="$2"
    shift 2
    # Use python3 for reliable multi-line substitution
    content="$(printf '%s' "$content" | python3 -c "
import sys
content = sys.stdin.read()
key = '{{${key}}}'
val = open('/dev/stdin') if False else None
import os
# val passed via env
val = os.environ.get('_TMPL_VAL', '')
print(content.replace(key, val), end='')
" _TMPL_VAL="$val")"
  done

  write_if_changed "$dest" "$content"
}

# ---------------------------------------------------------------------------
# summary_track <action>
# action: created | updated | unchanged | skipped
# ---------------------------------------------------------------------------
summary_track() {
  case "$1" in
    created)   _SUMMARY_CREATED=$((_SUMMARY_CREATED + 1)) ;;
    updated)   _SUMMARY_UPDATED=$((_SUMMARY_UPDATED + 1)) ;;
    unchanged) _SUMMARY_UNCHANGED=$((_SUMMARY_UNCHANGED + 1)) ;;
    skipped)   _SUMMARY_SKIPPED=$((_SUMMARY_SKIPPED + 1)) ;;
    *) log_warn "Unknown summary action: $1" ;;
  esac
}

# ---------------------------------------------------------------------------
# summary_print — Print final counts
# ---------------------------------------------------------------------------
summary_print() {
  echo ""
  echo "Summary:"
  printf "  ${_GREEN}created${_RESET}:   %d\n" "$_SUMMARY_CREATED"
  printf "  ${_CYAN}updated${_RESET}:   %d\n" "$_SUMMARY_UPDATED"
  printf "  unchanged: %d\n" "$_SUMMARY_UNCHANGED"
  printf "  skipped:   %d\n" "$_SUMMARY_SKIPPED"
}

# ---------------------------------------------------------------------------
# parse_yaml_with_python <yaml_file> <python_expr>
# Evaluates python_expr against the parsed YAML data (variable: `data`)
# Returns the result as a string.
# ---------------------------------------------------------------------------
parse_yaml_with_python() {
  local yaml_file="$1"
  local expr="$2"
  python3 - "$yaml_file" <<PYEOF
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
result = eval("""$expr""")
if isinstance(result, (dict, list)):
    import json
    print(json.dumps(result))
else:
    print(result if result is not None else '')
PYEOF
}
