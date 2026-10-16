# AI CLI Workspace

> 全域 AI CLI 設定的單一來源（Claude Code、Codex CLI、Gemini CLI、Pi）。
> 共用行為、保留各 CLI 原生差異；僅支援 macOS。決策見 [ADR-0005](docs/adr/0005-global-config-single-source.md)。

The single source for **global** AI CLI configuration on the owner's Macs. Each CLI
gets the same instructions, the same must-match settings keys, the same MCP servers
(where supported), and read-only access to the CS knowledge vault. Native differences
are documented, not emulated. Forked from
[zeuikli/claude-code-workspace](https://github.com/zeuikli/claude-code-workspace).

## What it manages

| Source | Claude Code | Codex CLI | Gemini CLI | Pi |
|---|---|---|---|---|
| `tools/instructions/AGENTS.md` (symlink) | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `~/.gemini/GEMINI.md` | `~/.pi/agent/AGENTS.md` |
| `tools/settings/managed.json` (key merge) | `settings.json` | `config.toml` | `settings.json` | `settings.json` |
| `tools/mcp/servers.json` (native `mcp add`) | ✓ | ✓ | ✓ (disabled in untrusted folders by Gemini) | — no MCP |
| zkfy vault tooling | `query` skill (`~/.claude/skills`) | `query` skill (`~/.agents/skills`) | `query` skill (`~/.agents/skills`) | `query` skill (`~/.agents/skills`) |

Not managed: credentials, sessions, plugin choices, local approvals/trust, per-project rules.

## Set up a Mac

Requires Python 3.11+ (stock `/usr/bin/python3` is too old: `brew install python`).

```bash
git clone <this repo> && git clone https://github.com/jasonsie/zkfy.git
export ZKFY_DIR=/path/to/zkfy ZKFY_VAULT=/path/to/vault   # optional: vault retrieval
bash scripts/install.sh --dry-run      # review
bash scripts/install.sh                # apply (backs up first)
bash scripts/healthcheck.sh            # verify live state
```

Claude plugins are a per-machine choice, not managed here. The current set:

```bash
claude plugin marketplace add https://github.com/jasonsie/zkfy.git
for p in zkfy@zkfy-marketplace pyright-lsp@claude-plugins-official typescript-lsp@claude-plugins-official; do
  claude plugin install "$p"
done
```

`--target=claude|codex|gemini|pi` limits the run; `--instructions-only` links instructions only.
Unknown existing instruction files are refused until reviewed (`--replace-instructions`);
see [global instructions](docs/global-instructions.md). Backups go to
`~/.local/state/ai-cli-workspace/`.

## Change something

- Instructions: edit `tools/instructions/AGENTS.md` (live immediately via the symlinks).
- A setting that must match on every Mac: add it to `tools/settings/managed.json`, rerun install.
- A shared MCP server: add it to `tools/mcp/servers.json` (no secrets), rerun install.
- Anything machine-specific: change it in the CLI itself; the installer leaves it alone.

Maintainer notes: [`AGENTS.md`](AGENTS.md). Upstream CLI docs are mirrored under
`docs/<cli>/upstream/` by `scripts/sync-cli-docs.sh`.

## License

MIT License
