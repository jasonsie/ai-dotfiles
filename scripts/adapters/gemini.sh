#!/usr/bin/env bash
# scripts/adapters/gemini.sh — Generate ~/.gemini/settings.json and related files
#
# Entry point: gemini_adapter_run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

WORKSPACE_DIR="${WORKSPACE_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# ---------------------------------------------------------------------------
# Build Gemini hooks JSON
# ---------------------------------------------------------------------------
_gemini_build_hooks_json() {
  python3 - "${WORKSPACE_DIR}/tools/hooks/manifest.yaml" "${WORKSPACE_DIR}" <<'PYEOF'
import sys, json, yaml

with open(sys.argv[1]) as f:
    manifest = yaml.safe_load(f)

workspace_dir = sys.argv[2]
events   = manifest.get('events', {})
matchers = manifest.get('matchers', {})

hooks_obj = {}

for event_key, event_data in events.items():
    gemini_event = event_data.get('gemini')
    if not gemini_event:
        continue

    script = event_data.get('script', '')
    matcher = (matchers.get(event_key, {}) or {}).get('gemini', '') or ''

    command = (
        'WORKSPACE_CLI_NAME=gemini '
        'WORKSPACE_DIR="{workspace}" '
        'bash "{workspace}/tools/hooks/{script}"'
    ).format(workspace=workspace_dir, script=script)

    entry = {
        "matcher": matcher,
        "command": command
    }

    if gemini_event not in hooks_obj:
        hooks_obj[gemini_event] = []
    hooks_obj[gemini_event].append(entry)

print(json.dumps(hooks_obj, indent=2))
PYEOF
}

# ---------------------------------------------------------------------------
# Build Gemini MCP JSON
# ---------------------------------------------------------------------------
_gemini_build_mcp_json() {
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
    if enabled and 'gemini' not in enabled:
        continue

    stype = srv.get('type', 'stdio')
    if stype == 'http':
        result[name] = {"type": "http", "url": srv.get('url', '')}
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
# Render settings.json using Python (avoids quote-substitution bugs)
# ---------------------------------------------------------------------------
_gemini_render_settings() {
  local hooks_json="$1"
  local mcp_json="$2"

  python3 - "${WORKSPACE_DIR}/tools/settings/gemini.json.tmpl" \
            "${hooks_json}" "${mcp_json}" <<'PYEOF'
import sys, json

with open(sys.argv[1]) as f:
    obj = json.load(f)

obj['hooks']      = json.loads(sys.argv[2])
obj['mcpServers'] = json.loads(sys.argv[3])

print(json.dumps(obj, indent=2, ensure_ascii=False))
PYEOF
}

# ---------------------------------------------------------------------------
# Convert an agent .md file to a Gemini skill SKILL.md
# ---------------------------------------------------------------------------
_agent_md_to_gemini_skill() {
  local agent_file="$1"
  local skill_dir="$2"

  python3 - "$agent_file" "$skill_dir" <<'PYEOF'
import sys, re, os

agent_path = sys.argv[1]
skill_dir  = sys.argv[2]

with open(agent_path) as f:
    raw = f.read()

# Parse YAML frontmatter if present
fm = {}
body = raw
fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', raw, re.DOTALL)
if fm_match:
    import yaml
    try:
        fm = yaml.safe_load(fm_match.group(1)) or {}
    except Exception:
        pass
    body = raw[fm_match.end():]

name = fm.get('name', os.path.basename(agent_path).replace('.md', ''))
description = fm.get('description', '')

skill_md = f"""---
name: agent-{name}
description: "{description}"
type: agent-wrapper
---

{body.strip()}
"""

os.makedirs(skill_dir, exist_ok=True)
out_path = os.path.join(skill_dir, 'SKILL.md')
with open(out_path, 'w') as f:
    f.write(skill_md)

# Mark this directory as workspace-managed so stale cleanup can find it
# and so future installs don't mistake it for user content.
with open(os.path.join(skill_dir, '.workspace-managed'), 'w') as f:
    f.write('managed-by: scripts/install.sh\n')

print(out_path)
PYEOF
}

# ---------------------------------------------------------------------------
# Convert a command .md file to Gemini command TOML
# ---------------------------------------------------------------------------
_command_md_to_gemini_toml() {
  local cmd_file="$1"
  local out_path="$2"

  python3 - "$cmd_file" "$out_path" <<'PYEOF'
import sys, re, os

cmd_path = sys.argv[1]
out_path = sys.argv[2]

with open(cmd_path) as f:
    raw = f.read()

fm = {}
body = raw
fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', raw, re.DOTALL)
if fm_match:
    import yaml
    try:
        fm = yaml.safe_load(fm_match.group(1)) or {}
    except Exception:
        pass
    body = raw[fm_match.end():]

description = fm.get('description', '')
body_stripped = body.strip()

# TOML triple-quoted string: escape backslashes and triple-quotes
body_toml = body_stripped.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')

toml_content = f'description = "{description}"\nprompt = """\n{body_toml}\n"""\n'

os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
with open(out_path, 'w') as f:
    f.write(toml_content)
PYEOF
}

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
gemini_adapter_run() {
  log_info "=== Gemini adapter ==="

  # 1. Ensure directories
  ensure_dir "${HOME}/.gemini"
  ensure_dir "${HOME}/.gemini/skills"
  ensure_dir "${HOME}/.gemini/commands"

  # 2. Copy each local skill (workspace-managed, marker-tracked)
  for skill_dir in "${WORKSPACE_DIR}/tools/skills"/*/; do
    skill_name="$(basename "$skill_dir")"
    # Only copy skills that have a SKILL.md
    if [ -f "${skill_dir}/SKILL.md" ]; then
      ensure_copied_tree "${WORKSPACE_DIR}/tools/skills/${skill_name}" \
                         "${HOME}/.gemini/skills/${skill_name}"
    fi
  done

  # 3. Convert agents to Gemini skills
  for agent_file in "${WORKSPACE_DIR}/tools/agents"/*.md; do
    [ -f "$agent_file" ] || continue
    agent_name="$(basename "$agent_file" .md)"
    local_skill_dir="${HOME}/.gemini/skills/agent-${agent_name}"

    if is_dry_run; then
      log_info "[dry-run] would generate agent skill: ${local_skill_dir}/SKILL.md"
      summary_track created
    else
      _agent_md_to_gemini_skill "$agent_file" "$local_skill_dir" >/dev/null
      log_ok "Generated agent skill: ${local_skill_dir}/SKILL.md"
      summary_track created
    fi
  done

  # 3b. Prune stale workspace-managed skills (both real + agent-wrapper).
  # Build the allowlist of basenames that should exist after this run.
  local valid_skill_names=()
  for skill_dir in "${WORKSPACE_DIR}/tools/skills"/*/; do
    [ -f "${skill_dir}/SKILL.md" ] || continue
    valid_skill_names+=("$(basename "$skill_dir")")
  done
  for agent_file in "${WORKSPACE_DIR}/tools/agents"/*.md; do
    [ -f "$agent_file" ] || continue
    valid_skill_names+=("agent-$(basename "$agent_file" .md)")
  done
  if [ ${#valid_skill_names[@]} -gt 0 ]; then
    prune_stale_managed_by_name "${HOME}/.gemini/skills" "${valid_skill_names[@]}"
  fi

  # 4. Convert commands to Gemini TOML
  for cmd_file in "${WORKSPACE_DIR}/tools/commands"/*.md; do
    [ -f "$cmd_file" ] || continue
    cmd_name="$(basename "$cmd_file" .md)"
    toml_path="${HOME}/.gemini/commands/${cmd_name}.toml"

    if is_dry_run; then
      log_info "[dry-run] would generate command: ${toml_path}"
      summary_track created
    else
      ensure_dir "${HOME}/.gemini/commands"
      _command_md_to_gemini_toml "$cmd_file" "$toml_path"
      log_ok "Generated command: ${toml_path}"
      summary_track created
    fi
  done

  # 5. Build and render settings.json
  log_info "Building Gemini hooks block..."
  local hooks_json
  hooks_json="$(_gemini_build_hooks_json)"

  log_info "Building Gemini MCP block..."
  local mcp_json
  mcp_json="$(_gemini_build_mcp_json)"

  log_info "Rendering ~/.gemini/settings.json..."
  local rendered
  rendered="$(_gemini_render_settings "$hooks_json" "$mcp_json")"

  write_if_changed "${HOME}/.gemini/settings.json" "$rendered"

  # 6. Validate JSON
  if ! is_dry_run && [ -f "${HOME}/.gemini/settings.json" ]; then
    if python3 -c "import json,sys; json.load(open(sys.argv[1]))" \
               "${HOME}/.gemini/settings.json" 2>/dev/null; then
      log_ok "~/.gemini/settings.json is valid JSON"
    else
      log_err "~/.gemini/settings.json failed JSON validation!"
    fi
  fi

  log_ok "Gemini adapter done."
}
