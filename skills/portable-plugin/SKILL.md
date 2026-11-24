---
name: portable-plugin
description: "Plugins that run in Claude Code, Codex, Pi and Antigravity from one repo: the rules a plugin's files follow, the check, and the release. Use when building or changing a plugin meant for all four CLIs, releasing one, or when a plugin works in Claude Code but not in another CLI."
---

# Portable plugin

A plugin lives in its own GitHub repo, one plugin at the repo root, in the Claude Code plugin
format. ai-dotfiles installs it into each CLI through that CLI's own plugin manager, at the
**release tag** its **pin** names in ai-dotfiles' `config/plugins.json`: Claude Code and Codex
from its marketplace, Antigravity by loading or converting it, Pi as a package. What then works
in each CLI is up to the plugin's own files. A feature a CLI cannot load as shipped is a
**gap**: fill it with that CLI's own feature where one exists, otherwise name it in the README's
support table.

The facts below were checked on 2026-11-05 with Claude Code 2.1.318, Codex 0.166, Antigravity
1.4.4 and Pi 1.0.2; the `upstream-docs` skill holds each CLI's current docs.

## Steps

1. **Change** the plugin by the rules below. Done when every rule holds or its gap is in the
   README's support table.
2. **Check**, from the plugin folder. Done when all four pass:
   - `claude plugin validate .` reports no error.
   - `agy plugin validate --strict .` reports no error. Three warnings are expected in a repo that also
     serves Claude Code and Codex, and only these: `.mcp.json`, `hooks/hooks.json` and a root `AGENTS.md`
     are "never loaded" by Antigravity. Any other warning is a defect.
   - Every frontmatter (skills, agents, commands) loads with a strict YAML parser: the YAML
     check below prints nothing and exits 0. Pi skips a skill that fails, silently, and
     `claude plugin validate` flags only agents.
   - The trial install below lists every skill in every CLI. Codex and Pi have no validator:
     this listing is their check.
3. **Release**: bump `version` in `.claude-plugin/plugin.json`, merge, then run
   `claude plugin tag --push` from the plugin folder. Then edit the plugin's pin in ai-dotfiles'
   `config/plugins.json` and run `ai-dotfiles install`. Done when the tag is on GitHub and
   `ai-dotfiles check` is healthy.

## Rules

- **Release tags** are `<name>--v<version>`, made by `claude plugin tag --push`, which checks
  that `plugin.json` and the marketplace entry agree, needs a clean tree and refuses an existing
  tag. Every CLI installs that tag, and Claude resolves plugin dependency ranges against these
  tags.
- **One version**, in `.claude-plugin/plugin.json`. The entry in `.claude-plugin/marketplace.json`
  points at `./` and leaves `version` out; Claude's validator warns when there are two.
- **Strict-YAML frontmatter**: write `description` and any other value with punctuation as a
  double-quoted string. A plain value holding `: ` breaks the parse; Pi then skips the skill and
  Antigravity the agent.
- **Skills, not commands**: every entry point is a skill, `skills/<name>/SKILL.md`, its `name`
  equal to its folder. Codex and Pi load no `commands/`; Antigravity turns commands into
  `<plugin>-cmd-<name>` skills only when it converts a plugin, which the native manifest below
  stops.
- **Paths relative to the skill folder**: a skill names bundled files from its own folder, such
  as `../../scripts/clip_note.py`. Only Claude fills in `${CLAUDE_PLUGIN_ROOT}` in skill, command
  and agent text; Codex sets it for hook commands only, Antigravity and Pi never, so elsewhere it
  reads as an empty path.
- **Other skills by bare name**: write "the `query` skill", never `zkfy:query`. Claude and Codex
  list plugin skills as `<plugin>:<skill>`; Antigravity and Pi list the bare name.
- **Commands on PATH in `bin/`**: an executable that finds its own files through its resolved
  path, since it runs through a symlink. Claude puts a plugin's `bin/` on its shell's PATH;
  ai-dotfiles links each `bin/` file into `~/.local/bin` for every CLI. Callers, other plugins
  included, run the bare name: the installed copy moves with every version.
- **Settings outside the plugin**: every version replaces the installed copy, read-only in
  Antigravity, so user settings live in `~/.config/<plugin>/`.
- **Hooks**: `hooks/hooks.json` in Claude's format serves Claude and Codex. Codex sets
  `CLAUDE_PLUGIN_ROOT` for them, matches its `apply_patch` as `Edit|Write`, and runs a plugin's
  hooks only after the user trusts them in `/hooks`. Antigravity needs its own `hooks.json` at
  the plugin root: named groups, its own tool names (`write_to_file`, `replace_file_content`,
  `multi_replace_file_content`, `run_command`; ai-dotfiles' `scripts/agent_hooks.py` keeps the
  current list), the plugin root as working directory, relative script paths. Pi has no hook
  file: an extension in `extensions/` calls the same scripts from `pi.on("tool_call", ...)` and
  returns `{ block: true, reason }` to refuse a call.
- **MCP servers**: `.mcp.json` serves Claude and Codex. Antigravity needs `mcp_config.json` at
  the plugin root, a remote server under `url` or `serverUrl`; its converter drops a remote
  server's URL. Pi loads no plugin MCP server: the Pi extension registers each one with
  `pi.registerMcpServer(name, config)`.
- **A native manifest for Antigravity**: `.antigravity-plugin/plugin.json` (`name` in kebab-case,
  `version`, `description`, `author`) makes `agy plugin install` load the plugin as is, reading
  `skills/`, `agents/`, `rules/`, `hooks.json` and `mcp_config.json` at the root. Without it,
  Antigravity converts the Claude format, which breaks hooks and remote MCP servers.
- **Agents Antigravity accepts**: `name` in the frontmatter (Claude takes it from the filename;
  Antigravity skips a nameless agent) and `model` `inherit` or left out. Claude's `sonnet` and
  `opus` are not Antigravity tiers, so it skips such an agent. A prompt file that a general
  subagent reads can live outside `agents/`, where no CLI loads it as an agent.
- **Skill bodies under 24000 bytes**: Antigravity loads only the first 24000 bytes of a
  `SKILL.md`; move detail into files the skill points at.
- **Steps without a subagent**: a step that delegates to a subagent says what to do in a CLI
  without one, as in Pi: read the agent file and do the work in the session.
- **Dependencies** go in `plugin.json` under `dependencies`, with a range. Only Claude acts on
  them; ai-dotfiles lists each dependency with its own pin and stops an install whose pins
  break a range.
- **Pi package**: Pi installs the repo as a package and loads `skills/`, `extensions/` and
  `prompts/` by convention; a `package.json` with a `pi` key is needed only to load other
  folders.
- **README support table**: a row per feature (skills, commands on PATH, hooks, MCP servers,
  agents), a column per CLI, each gap named.

## YAML check

Run from the plugin folder; it needs PyYAML (`python3 -m pip install pyyaml`). Each failing file
is printed with the parser's reason.

```bash
python3 - <<'EOF'
import glob, sys, yaml
bad = 0
for path in sorted(glob.glob('skills/*/SKILL.md') + glob.glob('agents/*.md') + glob.glob('commands/*.md')):
    try:
        yaml.safe_load(open(path).read().split('\n---', 1)[0].removeprefix('---'))
    except yaml.YAMLError as error:
        bad += 1
        print(f'{path}: {error}')
sys.exit(1 if bad else 0)
EOF
```

## Trial install

Run from the plugin folder; each line uses a throwaway home, so the real config stays as it is.
Read `<marketplace>` from `.claude-plugin/marketplace.json`.

```bash
( export CLAUDE_CONFIG_DIR="$(mktemp -d)"; claude plugin marketplace add "$PWD" && claude plugin install <name>@<marketplace> && claude plugin list --json )
( export CODEX_HOME="$(mktemp -d)"; codex plugin marketplace add "$PWD" && codex plugin add <name>@<marketplace> && codex debug prompt-input hi | grep -o '<name>:[a-z0-9-]*' | sort -u )
( export HOME="$(mktemp -d)"; agy plugin install "$PWD" && agy plugin list --json )
( export PI_CODING_AGENT_DIR="$(mktemp -d)"; pi install "$PWD" && (echo '{"type":"get_commands"}'; sleep 8) | pi --mode rpc --no-session | grep -o '"skill:[^"]*"' )
```

Pi's line holds stdin open for 8 seconds, the time Pi takes to start and answer; an empty
listing on a slow start means raise the `sleep`, not that the skills failed.

A released tag installs the same way from GitHub: `'<owner>/<repo>#<tag>'` for Claude,
`<owner>/<repo> --ref <tag>` for Codex, `https://github.com/<owner>/<repo>/tree/<tag>` for
Antigravity (it ignores a `#<tag>` suffix), `git:github.com/<owner>/<repo>@<tag>` for Pi.
