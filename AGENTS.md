# ai-dotfiles — maintainer notes

This repo is the single source for the owner's **global** AI CLI setup: Claude Code,
Codex CLI, Pi, and Antigravity. The mechanism and layout are in
[docs/how-it-works.md](docs/how-it-works.md); earlier decisions are in git history.
`CLAUDE.md` links to this file.

## Map

| Path | What | Applied by |
|---|---|---|
| `config/ai-clis.json` | Which CLIs are on, and where each reads things; the desired state | every step, via `scripts/install/installer.py` |
| `config/global-agents.md` | Global rules for every CLI, live through links | `scripts/install/instructions.py` |
| `config/cli-settings.json` | Per-CLI `enforce` and `default` keys | `scripts/install/settings.py` |
| `config/mcp-servers.json` | Shared MCP servers | `scripts/install/mcp.py` |
| `config/plugins.json` | The plugin list: each plugin's GitHub source, pin (exact version) and target CLIs | `scripts/install/plugins.py` |
| `config/upstream-docs.json` | The documentation sources mirrored for agents: each CLI's docs, Google's and Meta's style and docs-writing guides, a `when` label per page | `scripts/upstream/sync-upstream.py` (weekly workflow) |
| `skills/` | Shared skills; `skills.lock` pins adapted upstream skills | `scripts/install/skills.py` |
| `skills/daily-log/` | The `daily-log` command (the daily logger's grammar and writer) and `day_pass.py`, the day pass: the evidence and, with `--write`, the session that writes from it | `scripts/install/skills.py` (links), `scripts/install/launchd.py` (the 04:00 LaunchAgent) |
| `scripts/agent_sessions.py` | Every CLI's session store (transcripts) behind one interface, for the day pass | — |
| `skills/worktree-guard/` | The hook that moves a session clashing with another in one worktree into a linked worktree, and the `ai-dotfiles worktree` commands | `scripts/install/hooks.py` (hook entries) |
| `skills/small-commits/` | The hook that gates `git commit` on size (300 lines warn, 600 wall), subject and trailers, and the `ai-dotfiles commit check` command | `scripts/install/hooks.py` (hook entries), `scripts/ai-dotfiles` (`commit check`) |
| `skills/git/` | A bundle: the git step skills (`push-branch`, `open-pr`, `approve-pr`, `archive-tag`, `merge-pr`, `prune-branch`), each with its own script, and `approve`, which runs them in order; `scripts/git_run.py` is the runner they share | `scripts/install/skills.py` (each linked by its own name), `scripts/ai-dotfiles` (`approve`, `git <step>`) |
| `scripts/agent_hooks.py` | Every CLI's hook format behind one interface, for the skills' hooks; `agent_hooks.ts` is Pi's extension for all of them | `scripts/install/skills.py` (Pi's link) |
| `scripts/ai-dotfiles` | Global command: `install`, `update`, `uninstall`, `check`, `worktree`, `commit`, `approve`, `git` | `scripts/install/skills.py` |
| `scripts/install/installer.py` | What every step shares: reading `ai-clis.json`, safe writes | — |
| `scripts/install/hooks.py` | One hook entry per event in each CLI's native hook file; ours are found by their command; retired ones taken out | — |
| `scripts/install/plugins.py` | Each listed plugin at its release tag through each CLI's own plugin manager (Pi, Antigravity and Codex so far); a receipt tells installed from taken over; every outside command through one runner | — |
| `scripts/install/launchd.py` | The daily-log pass as a LaunchAgent, `claude` path and PATH rendered at install | — |
| `docs/upstream/` | Machine-written docs mirrors with their indexes (`INDEX.md`, `MIRROR-INDEX.*`), and skill catalogs | `scripts/upstream/` (weekly workflow) |
| `docs/onboarding.md` | This repo's onboarding report | `skills/onboard/` (`/onboard`) |
| `docs/agents/` | Where the engineering skills (`to-spec`, `to-tickets`, `triage`) publish and read: issue tracker, triage labels, domain docs | `skills/setup-agent-skills/` (`/setup-agent-skills`) |
| `scripts/tests/` | Unit tests for the scripts and the skills' helpers | — |
| `LICENSE`, `THIRD-PARTY-NOTICES.md`, `LICENSES/` | This repo's MIT license; every other author's license (adapted skills, docs mirrors) and the license texts | — |

`scripts/install.sh` runs the seven install steps, `scripts/uninstall.sh` reverses them;
`scripts/healthcheck.sh` verifies live state. `docs/` holds `how-it-works.md`, the mirror,
`onboarding.md`, this repo's report from `/onboard`, and `agents/`, the engineering skills'
setup.

## Rules for changes

- Shared behavior, native differences: do not emulate a feature a CLI lacks; document it.
- `config/global-agents.md` holds only rules that apply in every repository and every CLI.
  Keep it free of `@` imports and HTML comments: Claude parses them, the other CLIs do not.
- Never symlink a CLI's settings file (the CLIs write back to them); add keys to
  `cli-settings.json`, under `enforce` for safety settings or `default` for model choices.
- Logic two skills need lives in one skill (its `scripts/`); the others import it, never copy
  it. Code every step of a bundle needs goes in the bundle's `scripts/`. A bundle
  (`skills/git/`) is this repo's grouping only: the CLIs read one level of skill folders, so
  the installer links each skill in it by its own name.
- Lists live in `config/`: CLIs and their paths in `ai-clis.json`, documentation sources in
  `upstream-docs.json`; scripts keep only how each is applied.
- Never edit `docs/upstream/` by hand; the weekly sync rebuilds it. Agents read it through
  the `upstream-docs` skill; `collect-docs` adds a source.
- A newer upstream version of a pinned skill replaces ours: remove it, add theirs, re-apply
  its `local_edits` from `skills/skills.lock`, and update `which-skill` (a test checks it).
- Keep `config/` and `scripts/` free of machine paths (`/Users/<name>`, `/opt/homebrew`);
  the healthcheck enforces this.
- No credentials in this repo. Per-project rules belong to each project, not here.
- A new adapted skill or docs source gets a row in `THIRD-PARTY-NOTICES.md` and, for a new
  license, its text in `LICENSES/`.
- Every installer writes by default, previews with `--dry-run`, has `--uninstall`, is
  idempotent, backs up before writing, refuses to overwrite what it did not create, and
  rolls back on failure. Keep it that way and test it.

## Verify

```bash
python3 -m unittest discover -s scripts/tests      # Python 3.11+
shellcheck scripts/*.sh scripts/ai-dotfiles
bash scripts/install.sh --dry-run                  # expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```

## Agent skills

### Issue tracker

GitHub Issues on `jasonsie/ai-dotfiles`, through `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: the glossary and standing decisions are in `docs/how-it-works.md`; a design in progress is in `docs/plans/`. See `docs/agents/domain.md`.
