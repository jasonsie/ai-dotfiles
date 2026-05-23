#!/usr/bin/env bash
# scripts/install.sh — Cross-AI-CLI workspace installer
#
# Usage:
#   bash scripts/install.sh [--target=all|claude|gemini|codex] [--dry-run] [--force] [--help]
#
# Targets:
#   all    (default) — run all adapters
#   claude — regenerate .claude/settings.json + ~/.claude/CLAUDE.md
#   gemini — generate ~/.gemini/settings.json and related files
#   codex  — generate ~/.codex/config.toml and related files
#
# Rules generation always runs, regardless of --target.

set -euo pipefail

VERSION="1.0.0"

# ---------------------------------------------------------------------------
# Locate repo root
# ---------------------------------------------------------------------------
INSTALLER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WORKSPACE_DIR
WORKSPACE_DIR="$(cd "${INSTALLER_SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TARGET="all"
export DRY_RUN=0
export FORCE=0

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
workspace installer v${VERSION}

Usage: bash scripts/install.sh [OPTIONS]

Options:
  --target=TARGET   Which adapter(s) to run (default: all)
                    Values: all | claude | gemini | codex
  --dry-run         Print intended actions without making changes
  --force           Force overwrites even if content matches
  --help            Show this help message

Examples:
  bash scripts/install.sh
  bash scripts/install.sh --target=claude
  bash scripts/install.sh --target=claude --dry-run
  bash scripts/install.sh --target=gemini --dry-run

After installation, verify with:
  bash scripts/healthcheck.sh
EOF
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --target=*)  TARGET="${arg#--target=}" ;;
    --dry-run)   DRY_RUN=1 ;;
    --force)     FORCE=1 ;;
    --help|-h)   usage; exit 0 ;;
    *)
      printf "[ERR] Unknown argument: %s\n" "$arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# Validate target
case "$TARGET" in
  all|claude|gemini|codex) ;;
  *)
    printf "[ERR] Invalid target: %s (must be all|claude|gemini|codex)\n" "$TARGET" >&2
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# Source common helpers (for logging + summary)
# ---------------------------------------------------------------------------
source "${INSTALLER_SCRIPT_DIR}/adapters/_common.sh"

# ---------------------------------------------------------------------------
# Verify required dependencies
# ---------------------------------------------------------------------------
_check_deps() {
  if ! command -v python3 >/dev/null 2>&1; then
    log_err "python3 is required but not found. Please install Python 3.6+."
  fi
  # Verify python3 has yaml module (pyyaml)
  if ! python3 -c "import yaml" 2>/dev/null; then
    log_err "Python module 'yaml' (pyyaml) not found. Install with: pip3 install pyyaml"
  fi
  log_ok "Dependencies OK (python3 + pyyaml available)"
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
_print_banner() {
  echo ""
  echo "================================================="
  echo " Cross-AI-CLI Workspace Installer v${VERSION}"
  echo "================================================="
  printf " Workspace:  %s\n" "$WORKSPACE_DIR"
  printf " Target:     %s\n" "$TARGET"
  if [ "${DRY_RUN}" = "1" ]; then
    printf " Mode:       DRY RUN (no files will be written)\n"
  else
    printf " Mode:       LIVE\n"
  fi
  echo "================================================="
  echo ""
}

# ---------------------------------------------------------------------------
# Run adapter
# ---------------------------------------------------------------------------
_run_adapter() {
  local name="$1"
  local adapter_file="${INSTALLER_SCRIPT_DIR}/adapters/${name}.sh"

  if [ ! -f "$adapter_file" ]; then
    log_err "Adapter not found: ${adapter_file}"
    return 1
  fi

  # Source the adapter and call its entry point function
  source "$adapter_file"
  "${name}_adapter_run"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
_print_banner
_check_deps

case "$TARGET" in
  all)
    _run_adapter "claude"
    echo ""
    _run_adapter "gemini"
    echo ""
    _run_adapter "codex"
    ;;
  claude)
    _run_adapter "claude"
    ;;
  gemini)
    _run_adapter "gemini"
    ;;
  codex)
    _run_adapter "codex"
    ;;
esac

# Rules generation always runs last
echo ""
_run_adapter "rules"

# Pin the workspace path to a known location so Stage-2 launchers
# (skills, prompts, commands) can find scripts/init-project.sh without
# guessing — they read this file at runtime.
write_if_changed "${HOME}/.ai-cli-workspace-path" "$WORKSPACE_DIR"

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
summary_print

echo ""
if [ "${DRY_RUN}" = "1" ]; then
  log_info "Dry-run complete. Re-run without --dry-run to apply changes."
else
  log_ok "Installation complete."
  echo ""
  log_info "Verify installation: bash scripts/healthcheck.sh"
fi
echo ""
