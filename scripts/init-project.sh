#!/usr/bin/env bash
# scripts/init-project.sh — Stage 2 project-scope bootstrap.
#
# Runs inside a target project (CWD != workspace repo). Reads
# tools/profiles/*.yaml, lets the user multi-select dimensions, and
# writes a project-local .claude/CLAUDE.md as a strict additive layer
# on top of the user-global rules installed by Stage 1.
#
# Stage 1 → ~/.claude/, ~/.gemini/, ~/.codex/ (this script does NOT touch).
# Stage 2 → <project>/.claude/CLAUDE.md (this script's only output).
#
# Usage:
#   bash scripts/init-project.sh                        # interactive
#   bash scripts/init-project.sh --profile=frontend     # non-interactive
#   bash scripts/init-project.sh --profile=frontend,backend
#   bash scripts/init-project.sh --dry-run --profile=frontend
#
# Idempotent + marker-tracked: a .workspace-managed marker is written
# alongside the generated file. Re-runs refresh only marker-tagged
# output; user-edited CLAUDE.md (no marker) is left alone with a warn.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Reuse the adapter helpers (log_*, is_dry_run, write_if_changed,
# _assert_safe_rm_target, WORKSPACE_MARKER).
source "${WORKSPACE_DIR}/scripts/adapters/_common.sh"

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------
PROFILE_ARG=""
PROJECT_DIR="$(pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--profile=<name>[,<name>...]] [--dry-run] [--project=<path>]

Options:
  --profile=<csv>   Comma-separated profile names (non-interactive mode).
                    Profile files live in ${WORKSPACE_DIR}/tools/profiles/.
  --project=<path>  Target project directory. Defaults to current working dir.
  --dry-run         Print what would be written without touching the FS.
  -h, --help        Show this help.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --profile=*)  PROFILE_ARG="${arg#--profile=}" ;;
    --project=*)  PROJECT_DIR="$(cd "${arg#--project=}" && pwd)" ;;
    --dry-run)    DRY_RUN=1 ;;
    -h|--help)    usage; exit 0 ;;
    *)            log_err "Unknown argument: ${arg}"; usage; exit 1 ;;
  esac
done

PROFILES_DIR="${WORKSPACE_DIR}/tools/profiles"
if [ ! -d "$PROFILES_DIR" ]; then
  log_err "Profiles directory not found: ${PROFILES_DIR}"
  exit 1
fi

# Refuse to run inside the workspace repo itself — would clobber the
# hand-maintained CLAUDE.md/CONTEXT.md scaffolding.
if [ "$PROJECT_DIR" = "$WORKSPACE_DIR" ]; then
  log_err "Refusing to run inside the workspace repo (${WORKSPACE_DIR})."
  log_info "Run /init-project from a target project directory, or pass --project=<path>."
  exit 1
fi

# ---------------------------------------------------------------------------
# Discover available profiles
# ---------------------------------------------------------------------------
discover_profiles() {
  local f
  for f in "${PROFILES_DIR}"/*.yaml; do
    [ -f "$f" ] || continue
    basename "$f" .yaml
  done
}

available_profiles=()
while IFS= read -r p; do
  [ -n "$p" ] && available_profiles+=("$p")
done < <(discover_profiles)

if [ ${#available_profiles[@]} -eq 0 ]; then
  log_err "No profiles defined under ${PROFILES_DIR}"
  exit 1
fi

# ---------------------------------------------------------------------------
# Resolve which profiles to apply
# ---------------------------------------------------------------------------
selected_profiles=()

if [ -n "$PROFILE_ARG" ]; then
  # Non-interactive: split CSV, validate each.
  IFS=',' read -ra requested <<< "$PROFILE_ARG"
  for r in "${requested[@]}"; do
    found=0
    for a in "${available_profiles[@]}"; do
      if [ "$a" = "$r" ]; then
        selected_profiles+=("$r")
        found=1
        break
      fi
    done
    if [ "$found" = "0" ]; then
      log_err "Unknown profile: ${r}. Available: ${available_profiles[*]}"
      exit 1
    fi
  done
elif command -v gum >/dev/null 2>&1; then
  # Interactive (gum): multi-select with --no-limit.
  log_info "Select dimensions to apply (space to toggle, enter to confirm):"
  while IFS= read -r choice; do
    [ -n "$choice" ] && selected_profiles+=("$choice")
  done < <(gum choose --no-limit --header "Dimensions" "${available_profiles[@]}")
else
  # Interactive (fallback): read -p y/N per profile.
  log_info "gum not found — falling back to per-profile prompts."
  for a in "${available_profiles[@]}"; do
    read -r -p "Apply '${a}' profile? [y/N] " ans
    case "${ans:-n}" in
      y|Y|yes|YES) selected_profiles+=("$a") ;;
    esac
  done
fi

if [ ${#selected_profiles[@]} -eq 0 ]; then
  log_warn "No profiles selected — nothing to do."
  exit 0
fi

log_info "Selected profiles: ${selected_profiles[*]}"

# ---------------------------------------------------------------------------
# Build the union of skills from all selected profiles via Python (PyYAML).
# ---------------------------------------------------------------------------
profile_paths=()
for p in "${selected_profiles[@]}"; do
  profile_paths+=("${PROFILES_DIR}/${p}.yaml")
done

skills_union=$(python3 - "${profile_paths[@]}" <<'PYEOF'
import sys, re, yaml

paths = sys.argv[1:]
seen = set()
ordered = []
# Skill names must be filesystem-safe — they end up rendered into markdown
# and could in principle be re-used as path components by future profile
# logic. Reject anything that isn't a plain identifier.
ident = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')
for path in paths:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    for skill in (data.get('skills') or []):
        if not isinstance(skill, str) or not ident.match(skill):
            sys.stderr.write(f"[ERR] Invalid skill name in {path}: {skill!r}\n")
            sys.exit(1)
        if skill not in seen:
            seen.add(skill)
            ordered.append(skill)
print('\n'.join(ordered))
PYEOF
)

# ---------------------------------------------------------------------------
# Render the project-local CLAUDE.md
# ---------------------------------------------------------------------------
target_dir="${PROJECT_DIR}/.claude"
target_file="${target_dir}/CLAUDE.md"
marker_file="${target_dir}/${WORKSPACE_MARKER}"

# Build the content.
profile_list_md=""
for p in "${selected_profiles[@]}"; do
  profile_list_md+="- ${p}"$'\n'
done

skill_list_md=""
if [ -n "$skills_union" ]; then
  while IFS= read -r s; do
    [ -n "$s" ] && skill_list_md+="- ${s}"$'\n'
  done <<< "$skills_union"
fi

content=$(cat <<EOF
# CLAUDE.md — project-local context

> Generated by \`scripts/init-project.sh\` from ai-cli-workspace.
> User-global rules (~/.claude/) load before this file — treat this as a
> strict additive layer, not an override surface.

## Applied profiles

${profile_list_md}
## Surfaced skills

These skills were installed at the user-global layer and are recommended
for the selected dimensions. Trigger them by name when relevant:

${skill_list_md}
## Project notes

> Add project-specific instructions here. Anything written below this
> line is treated as hand-edited content — re-running \`/init-project\`
> will refresh the sections above but leave this section intact.

<!-- USER-CONTENT-BELOW -->
EOF
)

# ---------------------------------------------------------------------------
# Write semantics: marker-tracked, never clobber hand-edited content.
# ---------------------------------------------------------------------------
if [ -f "$target_file" ] && [ ! -f "$marker_file" ]; then
  log_warn "User-owned ${target_file} (no marker), refusing to overwrite."
  log_info "If you want /init-project to manage this file, delete it and re-run."
  exit 0
fi

if [ -f "$target_file" ] && [ -f "$marker_file" ]; then
  # Preserve hand-edited content below the sentinel. Require exactly one
  # sentinel — duplicates would silently drop content between them, and
  # absence means the user removed it (we refuse to guess what to keep).
  existing="$(cat "$target_file")"
  sentinel_count="$(printf '%s' "$existing" | grep -c '<!-- USER-CONTENT-BELOW -->' || true)"
  case "$sentinel_count" in
    1)
      user_section="${existing#*<!-- USER-CONTENT-BELOW -->}"
      content="${content}${user_section}"
      ;;
    0)
      log_err "Sentinel '<!-- USER-CONTENT-BELOW -->' missing from ${target_file}."
      log_info "Restore the sentinel or delete the file to regenerate from scratch."
      exit 1
      ;;
    *)
      log_err "Sentinel appears ${sentinel_count} times in ${target_file} (expected exactly 1)."
      log_info "Resolve manually before re-running."
      exit 1
      ;;
  esac
fi

if is_dry_run; then
  log_info "[dry-run] would write: ${target_file}"
  log_info "[dry-run] would write marker: ${marker_file}"
  echo "----- preview -----"
  printf '%s\n' "$content"
  echo "----- end preview -----"
  exit 0
fi

mkdir -p "$target_dir"
printf '%s\n' "$content" > "$target_file"
printf '%s\n' "managed-by: scripts/init-project.sh" > "$marker_file"
log_ok "Wrote: ${target_file}"
log_ok "Wrote marker: ${marker_file}"
