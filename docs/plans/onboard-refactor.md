# Onboard refactor

Status: in progress (2026-10-22). Branch `refactor/onboard` from `main`.

## Goal

Fix why `onboard` output looked wrong in session `430f4cab` (2026-10-22), then refactor
the onboarding family: tighter `SKILL.md` text (`onboard`, `architect`,
`iterative-retrieval`, `blueprint`), a restructured `facts.py`, and leftover cleanup.

## Diagnosis (high-effort agent, 2026-10-22)

The run used the current skill; install state is clean (all roots link to this checkout,
no `codemap` or `documentation-lookup` links). The file passes the structural checks.
Causes, most likely first:

1. Chat reply is a rewrite, not the file "as written" (`SKILL.md:95`): headings shifted,
   rows reworded. Step 5 asks for a verbatim print with risks interleaved, which forces
   recomposition.
2. File renders as run-on paragraphs: template rows and section fields are bare lines;
   graph fence not shown in the template.
3. Chat adds filler: `Risks: none found.`, and an "Open plan" self-grade against
   `docs/plans/onboard-report.md` (run in its own repo; no "add nothing else" rule).
4. `facts.py`: no entry points for executables below depth 0 outside `bin/`
   (`scripts/ai-dotfiles`); tree cut drops top-level folders; manifest `main`/`bin`
   targets listed without checking they exist; `scripts.*` flood the list; CODEMAPS tree
   and depth mismatch.
5. Spec gaps: a constant or path is not evidence for an edge; fan-out arrows; "What"
   runs long; where to list changes on rewrite; architect's onboard mode asks for a
   structure review onboard discards.

## Decisions

1. Fix both 1 and 2 without waiting on which one the user saw; both are cheap.
2. Reasoning-heavy work (diagnosis, `onboard`/`architect` spec) goes to a high-effort
   agent, per the user; agents own disjoint files, do not commit, return diffs for review.
3. `facts.py`: two commits. First the restructure, verified byte-identical by running the
   old and new script on the same trees in one command (forks are the main inputs).
   Then the bug fixes, each with a test. The `upstream/` language skew is left alone.
4. Contract changes update the skill's `skills.lock` `local_edits`.
5. Keep `.agents/onboarding.md` until the re-test (it is the failing run's evidence);
   remove `skills/codemap/` now.
6. Out of scope, told to the user: zkfy's Write hook `mkdir -p output`; marking
   `onboard-report.md` done.

## Changed files

- `skills/codemap/` removed (ignored `__pycache__` only)
- `c53828f` `iterative-retrieval`, `blueprint`: tightened, no behavior change
- `9333719` `facts.py` restructured; output identical on 4 repos and fixtures
- `2defcdf` `facts.py` fixes (entry points one folder down, tree never drops top-level,
  missing targets flagged, package.json scripts as a note, CODEMAPS any depth) + 7 tests
- `bee5764` `onboard`, `architect`, `skills.lock`: step 5 prints the file unchanged then
  risks; GFM template; one target per arrow; cite the linking line; architect's onboard
  mode returns debt and red flags only

Checks after `bee5764`: 141 tests OK; shellcheck only SC2016 info; installer preview 0
changes; healthcheck healthy.

## Checks

- `unittest`, `shellcheck`, `install.sh --dry-run`, healthcheck.
- `facts.py` restructure: old and new output identical on the three forks and this repo.
- Render: `pandoc -f gfm` of the report gives separate items for the opening, Index rows,
  and section fields, not one `<p>`.
- Chat equals file: a `claude -p` run in a fresh fork worktree, with tools allowed so
  `facts.py` runs; the printed report diffs clean against the file except the risks
  block and closing lines.

## Trial results (2026-10-22, `claude -p "/onboard"`, tools allowed)

Both: `facts.py` ran; 12 parts; `[n]` sets identical in all three parts; every citation
exists and points at the linking line; no risks in the file; `pandoc` gives list items
and one `<pre>`; chat ends with the path line and the question.

- Fresh clone of `forks/ai/dotfiles` `main`: chat body byte-identical to the file.
- `reference/dotfiles` (same repo, with the user's uncommitted edits): body identical,
  but one preamble line before it. Fixed: step 5 now says to start with the file's
  first line.

- Gap the user caught: both runs started inside the target, so `/onboard <path>` from
  another repo was untested, and the skill never tied ROOT to a named path. Fixed
  (`85a9b97`); re-run from `ai_dotfiles` as `/onboard .../reference/dotfiles`: report on
  dotfiles, written to `forks/ai/dotfiles/.agents/onboarding.md` (rewrite, change
  listed), chat identical to the file and starting with its header, `ai_dotfiles`
  report untouched.

## Next step

Open the PR. Left to the user: a Codex run, a repo over 12 parts (`firecrawl`), a
re-run (rewrite lists changes), a planted hand-written report, and a deep dive.
