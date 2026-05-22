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
# Workspace-managed marker filename — written into each installed dir so
# future installs can distinguish workspace-owned from user-added content.
# ---------------------------------------------------------------------------
WORKSPACE_MARKER=".workspace-managed"

# ---------------------------------------------------------------------------
# _expand_tilde <path>
# Safe ~ expansion without eval. Echoes the expanded path.
# ---------------------------------------------------------------------------
_expand_tilde() {
  local p="$1"
  case "$p" in
    "~")    printf '%s' "$HOME" ;;
    "~/"*)  printf '%s' "${HOME}/${p#\~/}" ;;
    *)      printf '%s' "$p" ;;
  esac
}

# ---------------------------------------------------------------------------
# _assert_safe_rm_target <path>
# Hard guard: never rm -rf empty, "/", $HOME, or a non-absolute path.
# Returns 1 (and logs) on suspect input.
# ---------------------------------------------------------------------------
_assert_safe_rm_target() {
  local p="$1"
  if [ -z "$p" ] || [ "$p" = "/" ] || [ "$p" = "$HOME" ] || [ "$p" = "${HOME}/" ]; then
    log_err "Refusing to rm suspect path: '${p}'"
    return 1
  fi
  case "$p" in
    /*) return 0 ;;
    *)  log_err "Refusing to rm non-absolute path: '${p}'"; return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# ensure_copied_tree <source_dir> <dest_dir>
# Copy a workspace-owned directory tree to dest_dir, dropping a
# .workspace-managed marker file so future runs can distinguish
# workspace-installed entries from user-added ones.
#
# Behaviour:
#   - If dest is a symlink (legacy install): remove the symlink, then copy.
#   - If dest is a regular dir without our marker: leave it alone (user-owned).
#   - If dest is a regular dir with our marker: refresh contents only if
#     they differ from source.
#
# Idempotency is achieved by diffing source against dest after copy.
# Marker write is atomic via a staging directory + mv, so an interrupted
# copy never leaves a managed dir without its marker.
# ---------------------------------------------------------------------------
ensure_copied_tree() {
  local source_dir="$1"
  local dest_dir
  dest_dir="$(_expand_tilde "$2")"
  local marker="$WORKSPACE_MARKER"

  if [ ! -d "$source_dir" ]; then
    log_err "ensure_copied_tree: source does not exist: ${source_dir}"
    return 1
  fi

  # Case 1: legacy symlink — remove the link (NOT the target) and fall through to copy.
  if [ -L "$dest_dir" ]; then
    if is_dry_run; then
      log_info "[dry-run] would migrate symlink to copy: ${dest_dir}"
      summary_track updated
      return 0
    fi
    rm "$dest_dir"
  # Case 2: existing dir without our marker — user-owned, skip.
  elif [ -d "$dest_dir" ] && [ ! -f "${dest_dir}/${marker}" ]; then
    log_warn "User-owned directory (no ${marker} marker), skipping: ${dest_dir}"
    summary_track skipped
    return 0
  # Case 3: existing managed dir — check if contents already match source.
  elif [ -d "$dest_dir" ] && [ -f "${dest_dir}/${marker}" ]; then
    if _tree_matches_source "$source_dir" "$dest_dir" "$marker"; then
      log_info "Unchanged: ${dest_dir}"
      summary_track unchanged
      return 0
    fi
    if is_dry_run; then
      log_info "[dry-run] would update managed dir: ${dest_dir}"
      summary_track updated
      return 0
    fi
    _assert_safe_rm_target "$dest_dir" || return 1
    rm -rf "$dest_dir"
  # Case 4: path exists but is neither a symlink nor a directory.
  elif [ -e "$dest_dir" ]; then
    log_warn "Path exists but is neither a symlink nor a directory, skipping: ${dest_dir}"
    summary_track skipped
    return 0
  # Case 5: nothing exists yet.
  else
    if is_dry_run; then
      log_info "[dry-run] would create copy: ${dest_dir}"
      summary_track created
      return 0
    fi
  fi

  # Atomic copy + marker write via staging dir.
  local parent staging
  parent="$(dirname "$dest_dir")"
  mkdir -p "$parent"
  staging="${dest_dir}.tmp.$$"
  # Clean up any prior staging crumb from a previous crash.
  if [ -e "$staging" ]; then
    _assert_safe_rm_target "$staging" || return 1
    rm -rf "$staging"
  fi
  # cp -RL dereferences nested symlinks so the dest is a self-contained tree
  # decoupled from tools/ — intentional, since the install model promises
  # ~/.codex and ~/.gemini are runtime copies, not live views into the repo.
  cp -RL "$source_dir" "$staging"
  printf '%s\n' "managed-by: scripts/install.sh" > "${staging}/${marker}"
  mv "$staging" "$dest_dir"
  log_ok "Copied: ${source_dir} -> ${dest_dir}"
  summary_track created
}

# ---------------------------------------------------------------------------
# _tree_matches_source <source_dir> <dest_dir> <marker_filename>
# Returns 0 if dest contains the same files+content as source (ignoring the
# marker file itself). Returns 1 on any diff.
# ---------------------------------------------------------------------------
_tree_matches_source() {
  local source_dir="$1"
  local dest_dir="$2"
  local marker="$3"

  # diff -rq is portable on macOS and Linux. Keep stderr separate so real
  # errors surface instead of being silently absorbed into the diff output.
  local diff_out diff_err
  diff_err="$(mktemp)"
  diff_out="$(diff -rq "$source_dir" "$dest_dir" 2>"$diff_err")" || true
  if [ -s "$diff_err" ]; then
    log_warn "diff stderr while comparing ${source_dir} vs ${dest_dir}: $(cat "$diff_err")"
  fi
  rm -f "$diff_err"

  # diff -rq output lines come in two forms; both end the marker reference
  # with a path separator or end-of-line. Match precisely on the basename:
  #   "Only in <dir>: .workspace-managed"
  #   "Files <a>/.workspace-managed and <b>/.workspace-managed differ"
  local residual
  residual="$(printf '%s\n' "$diff_out" | grep -vE "(: |/)${marker}( |$)" | grep -v '^$' || true)"
  [ -z "$residual" ]
}

# ---------------------------------------------------------------------------
# prune_stale_managed_by_name <dest_parent_dir> <valid_name_1> [<valid_name_2> ...]
# Remove subdirectories of dest_parent_dir that carry the .workspace-managed
# marker but whose basename is not in the supplied allowlist. Used when the
# dest dir receives content from multiple source roots (e.g. gemini skills
# fed by tools/skills/ AND tools/agents/).
#
# Refuses to run with an empty allowlist — that would prune every managed
# entry, which is almost certainly a caller bug rather than intent.
# ---------------------------------------------------------------------------
prune_stale_managed_by_name() {
  local dest_parent
  dest_parent="$(_expand_tilde "$1")"
  shift
  local marker="$WORKSPACE_MARKER"

  if [ "$#" -eq 0 ]; then
    log_err "prune_stale_managed_by_name: refusing to prune with empty allowlist (${dest_parent})"
    return 1
  fi

  [ -d "$dest_parent" ] || return 0

  local entry name keep allowed
  for entry in "$dest_parent"/*/; do
    [ -d "$entry" ] || continue
    name="$(basename "$entry")"

    # Only consider workspace-managed entries.
    [ -f "${entry}${marker}" ] || continue

    keep=0
    for allowed in "$@"; do
      if [ "$name" = "$allowed" ]; then
        keep=1
        break
      fi
    done
    [ "$keep" = "1" ] && continue

    if is_dry_run; then
      log_info "[dry-run] would prune stale managed dir: ${entry}"
      summary_track updated
      continue
    fi
    _assert_safe_rm_target "${entry%/}" || return 1
    rm -rf "$entry"
    log_ok "Pruned stale managed dir: ${entry}"
    summary_track updated
  done
}

# ---------------------------------------------------------------------------
# prune_stale_managed <dest_parent_dir> <source_parent_dir>
# Remove subdirectories of dest_parent_dir that carry the .workspace-managed
# marker but no longer have a corresponding entry under source_parent_dir.
# User-added directories (no marker) are left untouched.
# ---------------------------------------------------------------------------
prune_stale_managed() {
  local dest_parent
  dest_parent="$(_expand_tilde "$1")"
  local source_parent="$2"
  local marker="$WORKSPACE_MARKER"

  [ -d "$dest_parent" ] || return 0

  local entry name
  for entry in "$dest_parent"/*/; do
    [ -d "$entry" ] || continue
    name="$(basename "$entry")"

    # Only consider workspace-managed entries.
    [ -f "${entry}${marker}" ] || continue

    # Skip if source still exists.
    [ -d "${source_parent}/${name}" ] && continue

    if is_dry_run; then
      log_info "[dry-run] would prune stale managed dir: ${entry}"
      summary_track updated
      continue
    fi
    _assert_safe_rm_target "${entry%/}" || return 1
    rm -rf "$entry"
    log_ok "Pruned stale managed dir: ${entry}"
    summary_track updated
  done
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
