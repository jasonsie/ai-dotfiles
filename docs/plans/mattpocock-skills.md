# Skills from reference/skill (mattpocock/skills snapshot)

Status: active

## Goal

Bring the skills in `reference/skill/` (the `sieener/skill` fork: no own commits, a
snapshot of `mattpocock/skills` at `b843cb5`, 2026-04-30) into `skills/` as shared,
CLI-neutral skills, following this repo's rules.

## Decisions

1. **Kept (14):** `diagnose`, `grill-with-docs`, `improve-codebase-architecture`,
   `setup-matt-pocock-skills` (renamed, decision 4), `tdd`, `to-issues`, `to-prd`,
   `triage`, `zoom-out`, `caveman`, `write-a-skill`, `migrate-to-shoehorn`,
   `setup-pre-commit`, `edit-article`.
2. **Dropped (user, 2026-10-21):** the four `deprecated/*` (replaced inside the set);
   `grill-me` (existing `grilling` is its successor); `obsidian-vault` (Matt's machine
   path, overlaps the zkfy vault); `scaffold-exercises` (needs Matt's `ai-hero-cli`);
   `git-guardrails-claude-code` (hand-edits `~/.claude/settings.json`, Claude-only).
   Not tools, not ported: `.claude/`, `.agents/`, `.codebuddy/` (empty), `scripts/`
   (duplicates `install-skills.py`), `.out-of-scope/`, `docs/`, `CONTEXT.md`,
   `plugin.json`, bucket READMEs.
3. **Source and pin:** port the snapshot as asked, pin `mattpocock/skills@b843cb5ea74b1fe5e58a0fc23cddef9e66076fb8`
   (same repo as `grilling`; a frozen fork never reports drift). 16 of its files are gone
   at upstream HEAD (renamed: `diagnose`→`diagnosing-bugs`, `to-prd`→`to-spec`,
   `to-issues`→`to-tickets`, etc.), so `report-upstream.py` must report a 404 per path
   as "removed upstream" instead of failing the weekly run.
4. **Rename** `setup-matt-pocock-skills` → `setup-agent-skills`; update every mention.
   It edits `AGENTS.md` first (this repo's project-memory convention), else `CLAUDE.md`,
   else creates `AGENTS.md`.
5. **Port style** as `grilling`/`architect`: faithful text, minimal edits; upstream
   `LICENSE` and an attribution line per skill; CLI-neutral (no Agent tool or
   `subagent_type`; "a sub-agent where the CLI has one"); `/skill` → "the `skill`
   skill"; no `: ` in unquoted descriptions (Antigravity once failed on that); one
   `skills.lock` entry each, `path` listing every ported file.
6. **Explicit-only skills** (`zoom-out`, `setup-agent-skills` carry
   `disable-model-invocation: true`): Claude Code and Pi honour the key; Codex gets its
   native `agents/openai.yaml` with `policy.allow_implicit_invocation: false`;
   Antigravity has no documented equivalent, so they may load implicitly there.
7. **Branch:** `feat/mattpocock-skills` in worktree `../ai_dotfiles-mattpocock`, from
   `origin/main` (7ccebe5; #18 not merged yet). Upstream tracking unset.

## Changed files

- `docs/plans/mattpocock-skills.md`, `docs/how-it-works.md` (removed-upstream sentence;
  explicit-only skill row in the per-CLI table)
- `scripts/report-upstream.py`, `tests/test_report_upstream.py` (removed-upstream paths;
  a path missing at the pinned commit is an error; each diff capped at 20 lines, because
  the new pins took the skills section from 6.7K to 79.9K chars, over GitHub's 65,536
  PR-body limit; now 27K)
- `skills/<14 names>/` (each with upstream `LICENSE` + attribution line),
  `skills/{zoom-out,setup-agent-skills}/agents/openai.yaml`, `skills/skills.lock`

## Checks

- `python3 -m unittest discover -s tests`
- `shellcheck scripts/*.sh scripts/ai-dotfiles skills/diagnose/scripts/*.sh`
- `bash scripts/install.sh --dry-run` from the worktree (expect 14 new skills x CLI folders,
  plus repoint noise because ROOT differs)
- After merge: `install-skills.py --apply`, `bash scripts/healthcheck.sh`

Results (2026-10-21): `unittest` 100 OK; `shellcheck` only the existing SC2016 info in
`sync-cli-docs.sh` (`hitl-loop.template.sh` clean); live `section_skills()` run on the new
lock completes, every pinned path exists at `b843cb5`, 16 files reported removed;
`install-skills.py` preview: 14 new x 3 folders + repoint of 8 existing (worktree ROOT),
nothing refused; unedited skills differ from the fork only by the attribution line.
Ports done by hand, not sub-agents: copies plus ~15 targeted edits.

## Next step

1. ~~Report fix + test.~~ ~~Port the 14 skills.~~ ~~Lock entries, checks.~~ Done.
2. ~~Commit, PR.~~ Done: d4df649, PR #19.
3. After merge, in the main checkout: `python3 scripts/install-skills.py --apply`,
   `bash scripts/healthcheck.sh`; check one new skill loads per CLI (e.g. Codex
   `codex debug prompt-input "hi"` lists `tdd`, and does not list `zoom-out` implicitly);
   `git worktree remove ../ai_dotfiles-mattpocock`; mark this file `done`.
