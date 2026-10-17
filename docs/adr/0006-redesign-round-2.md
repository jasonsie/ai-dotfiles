# Global rules only where they apply everywhere; shared skills by symlink; reviewed upstream updates

Status: **Accepted** 2026-10-17. Amends [ADR-0005](0005-global-config-single-source.md);
supersedes [ADR-0004](0004-upstream-mirror-subdir.md). Decided in the round-2 interview
(Q17–Q31) recorded in `docs/plans/project-redesign.md` on branch `claude/project-redesign`.

## Context

ADR-0005 made this repo the single source of global configuration for Claude Code, Codex,
Gemini CLI, and Pi. By October 2026 the evidence had moved:

- Gemini CLI had not been used since May; Antigravity was installed; Pi had gained MCP
  and reads `~/.agents/skills`, which Codex reads too.
- The weekly docs sync failed silently: the Codex index moved (two syncs cut that mirror
  to 2–3 pages and pushed to `main`), and the Antigravity site was rebuilt, so its pages
  had not been refreshed since June.
- The 60-line global `AGENTS.md` loaded into every session of every project, and a CLI's
  memory feature could write through its link into the shared source.
- Managed model keys undid choices made in each CLI's own model menu.
- The vault tooling that the global instructions required was untracked in zkfy, so a
  fresh clone could not provide it.

## Decisions

| # | Decision |
|---|---|
| Q17 | Personal setup first; a toolkit for others comes later. Gemini CLI is no longer a target; `~/.gemini/GEMINI.md` stays linked because Antigravity reads it. Personal values stay in this repo. Upstream updates arrive as a weekly pull request. |
| Q18, Q23b | The global `AGENTS.md` holds only rules that apply in every repository and every CLI. Today that is one rule: task memory. |
| Q19, Q20 | Shared skills: `grilling` (adapted from mattpocock/skills, MIT) and `query` (zkfy's read-only vault skill, renamed from `vault-query` at its source). |
| Q21 | `query` and its engine stay owned by zkfy and are tracked there. |
| Q22 | Skills reach every CLI by symlinks from one source: `~/.claude/skills` (Claude), `~/.agents/skills` (Codex and Pi), `~/.gemini/config/skills` (Antigravity CLI and IDE). |
| Q23a | Task memory exists only for repository work, in `docs/plans/<task>.md` (or where the repository says). |
| Q23c | Project memory lives in the project's `AGENTS.md`; a `CLAUDE.md` links to it or imports it. |
| Q23d, Q34 | Engineering docs are deferred. The shared MCP server (context7) is registered in all four CLIs: through `mcp add` for Claude Code, Codex and Pi, and by merging `~/.gemini/config/mcp_config.json` for Antigravity, which has no such command. |
| Q24 | `managed.json` version 2: `enforce` keys (safety) are put back on every install; `default` keys (model choices) are written only while a CLI has none. |
| Q25 | The weekly pull request flags doc changes that touch this setup, using a deterministic script. |
| Q26, Q27 | Antigravity is supported, and its terminal sandbox is enforced. |
| Q28 | No end-to-end portability test beyond the installers' unit tests. |
| Q29 | `install.sh` previews by default; `--apply` writes. |
| Q30 | Leftovers (the other AI's plan copy, unused folders) were removed after a preview. |

## Consequences

- Mirrors live in `upstream/docs/<tool>/` (claude, codex, pi, antigravity), written only by
  `scripts/sync-cli-docs.sh`. Hand-written catalogs no longer sit beside them, so ADR-0004's
  `docs/<cli>/upstream/` split is no longer needed. Every source has a page floor below
  which the previous copy is kept.
- `.github/workflows/sync-cli-docs.yml` commits to the `upstream-sync` branch and opens or
  refreshes one pull request. `scripts/report-upstream.py` writes its description. The
  repository setting "Allow GitHub Actions to create and approve pull requests" must be on.
- `scripts/install-skills.py` (step 5 of `install.sh`) links `skills/<name>/`; adapted
  upstream skills are pinned in `skills/skills.lock`.
- A CLI's own memory or rule-saving feature must never write through the shared links;
  `~/.gemini/config/AGENTS.md` (where Antigravity appends rules) is never linked.
- Codex and Pi models chosen in their own menus persist; the healthcheck reports them as
  local choices.
