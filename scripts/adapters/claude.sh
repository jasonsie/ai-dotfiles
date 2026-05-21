#!/usr/bin/env bash
# scripts/adapters/claude.sh — Regenerate .claude/settings.json and ~/.claude/CLAUDE.md
#
# WARNING: This script FULLY overwrites .claude/settings.json on each run
#          (a .bak is saved on first run for safety). User-added keys will be
#          lost unless added to tools/settings/claude.json.tmpl.
#
# Entry point: claude_adapter_run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

WORKSPACE_DIR="${WORKSPACE_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# ---------------------------------------------------------------------------
# Build the hooks JSON object using Python
# Returns a JSON string representing the Claude hooks object.
# ---------------------------------------------------------------------------
_claude_build_hooks_json() {
  python3 - "${WORKSPACE_DIR}/tools/hooks/manifest.yaml" "${WORKSPACE_DIR}" <<'PYEOF'
import sys, json, yaml

manifest_path = sys.argv[1]
workspace_dir = sys.argv[2]

with open(manifest_path) as f:
    manifest = yaml.safe_load(f)

events   = manifest.get('events', {})
matchers = manifest.get('matchers', {})

# Debug-only events that must be wrapped in a CLAUDE_DEBUG guard
DEBUG_EVENTS = {'instructions-loaded', 'subagent-start', 'subagent-stop'}

hooks_obj = {}

for event_key, event_data in events.items():
    claude_event = event_data.get('claude')
    if not claude_event:
        continue  # null means skip

    script = event_data.get('script', '')
    matcher = (matchers.get(event_key, {}) or {}).get('claude', '') or ''

    # Build the bash command
    raw_cmd = (
        'WORKSPACE_CLI_NAME=claude '
        'WORKSPACE_DIR="{workspace}" '
        'bash "{workspace}/tools/hooks/{script}"'
    ).format(workspace=workspace_dir, script=script)

    if event_key in DEBUG_EVENTS:
        command = 'if [ -n "$CLAUDE_DEBUG" ]; then {cmd}; fi'.format(cmd=raw_cmd)
    else:
        command = raw_cmd

    entry = {
        "matcher": matcher,
        "hooks": [
            {
                "type": "command",
                "command": command
            }
        ]
    }

    hooks_obj[claude_event] = [entry]

print(json.dumps(hooks_obj, indent=2))
PYEOF
}

# ---------------------------------------------------------------------------
# Build the mcp_servers JSON object using Python
# ---------------------------------------------------------------------------
_claude_build_mcp_json() {
  python3 - "${WORKSPACE_DIR}/tools/mcp/servers.yaml" <<'PYEOF'
import sys, json, yaml

with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)

servers = data.get('servers') or []
result = {}

for srv in servers:
    name = srv.get('name')
    if not name:
        continue
    enabled = srv.get('enabled-for')
    # enabled-for defaults to all CLIs if not set
    if enabled and 'claude' not in enabled:
        continue

    stype = srv.get('type', 'stdio')
    if stype == 'http':
        result[name] = {
            "type": "http",
            "url": srv.get('url', '')
        }
    else:
        entry = {
            "type": "stdio",
            "command": srv.get('command', ''),
            "args": srv.get('args', [])
        }
        if srv.get('env'):
            entry['env'] = srv['env']
        result[name] = entry

print(json.dumps(result, indent=2))
PYEOF
}

# ---------------------------------------------------------------------------
# Build the final settings.json using Python (avoids quote-substitution bugs)
# ---------------------------------------------------------------------------
_claude_render_settings() {
  local hooks_json="$1"
  local mcp_json="$2"

  python3 - "${WORKSPACE_DIR}/tools/settings/claude.json.tmpl" \
            "${hooks_json}" "${mcp_json}" <<'PYEOF'
import sys, json

tmpl_path = sys.argv[1]
hooks_json = sys.argv[2]
mcp_json   = sys.argv[3]

with open(tmpl_path) as f:
    obj = json.load(f)

# Replace placeholder strings with real objects
hooks_obj = json.loads(hooks_json)
mcp_obj   = json.loads(mcp_json)

obj['hooks']       = hooks_obj
obj['mcp_servers'] = mcp_obj

print(json.dumps(obj, indent=2, ensure_ascii=False))
PYEOF
}

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
claude_adapter_run() {
  log_info "=== Claude adapter ==="

  local settings_dest="${WORKSPACE_DIR}/.claude/settings.json"
  local settings_bak="${WORKSPACE_DIR}/.claude/settings.json.bak"
  local home_claude="${HOME}/.claude/CLAUDE.md"

  # 1. Write ~/.claude/CLAUDE.md pointer (only if different)
  ensure_dir "${HOME}/.claude"
  local pointer_content="@${WORKSPACE_DIR}/CLAUDE.md"
  write_if_changed "${home_claude}" "${pointer_content}"

  # 2. Save .bak on first run (never overwrite existing .bak)
  if [ -f "$settings_dest" ] && [ ! -f "$settings_bak" ]; then
    if ! is_dry_run; then
      cp "$settings_dest" "$settings_bak"
      log_info "Backed up existing settings.json -> settings.json.bak"
    else
      log_info "[dry-run] would back up settings.json -> settings.json.bak"
    fi
  fi

  # 3. Build hooks JSON
  log_info "Building hooks block from tools/hooks/manifest.yaml..."
  local hooks_json
  hooks_json="$(_claude_build_hooks_json)"

  # 4. Build MCP JSON
  log_info "Building mcp_servers block from tools/mcp/servers.yaml..."
  local mcp_json
  mcp_json="$(_claude_build_mcp_json)"

  # 5. Render settings
  log_info "Rendering .claude/settings.json..."
  local rendered
  rendered="$(_claude_render_settings "$hooks_json" "$mcp_json")"

  # 6. Write if changed
  write_if_changed "$settings_dest" "$rendered"

  # 7. Validate JSON (skip in dry-run since file may not have been written)
  if ! is_dry_run && [ -f "$settings_dest" ]; then
    if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$settings_dest" 2>/dev/null; then
      log_ok "settings.json is valid JSON"
    else
      log_err "settings.json failed JSON validation!"
    fi
  fi

  log_ok "Claude adapter done."
}
