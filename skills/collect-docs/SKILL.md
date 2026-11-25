---
name: collect-docs
description: Add a documentation source to the ai-dotfiles mirror. Survey a GitHub org, repository or docs site for the guides wanted, write its entry in config/upstream-docs.json, sync and index it.
disable-model-invocation: true
---

# Collect docs

`$ARGUMENTS — <github org | owner/repo | docs site URL> [what to collect]`

`docs/upstream/` is machine-written from `config/upstream-docs.json`; this skill ends with one
new entry there, synced and indexed. Work in a worktree of ai-dotfiles: start with `ai-dotfiles
worktree new docs/<source>` and finish with the `ship-pr` skill, which opens the PR for review.

## 1. Scope

Settle with the user which documents (coding style, docs writing, code review, a tool's manual),
for which tasks (these become the `when` labels), and the source kind: `github` (files in
repositories), `llms` (a site whose `llms.txt` lists Markdown twins of its pages), `docs-json`
(a `docs.json` navigation in a repository). Done when one line says what a page must be about
to be included.

## 2. Survey

GitHub org or repository: `python3 <this skill folder>/survey.py <org | owner/repo> [--pattern REGEX]
[--files REGEX] [--json]` lists candidate files (repo, default branch, archived, fork, license,
last push, path, KB) from the repository inventory and a scan of each matching repository's
tree. A repository named outright lists every document file; in an org scan a repository whose
name was the match (`eng-practices`, `styleguide`) hides its guides behind plain file names, so
rescan it alone. An org above 1,000 repositories needs `--limit` (google is one). Then:

- `gh search code '"style guide" org:<org>'`, also with "coding conventions", "code style",
  "documentation style" and "writing guide": catches guides whose file names say nothing, and
  covers a repository whose tree listing the script reports as truncated.
- Read each candidate's first lines and headings (the raw URL, or
  `gh api repos/<o>/<r>/contents/<path>`). Keep a file that states rules. Record its branch,
  license (read the LICENSE file when GitHub detects none), last commit date, size, format.
- Sort every candidate: **sync**; **optional** (an agent-instruction file with one style section,
  a tool's rule configuration); **skip** with a reason (a fork carries its upstream project's
  guide; boilerplate CONTRIBUTING sections; formatter configuration; tooling; a UI styling
  system with "style" in its name).
- Note the enforcers beside each guide (`.clang-format`, `pylintrc`, an ESLint config) and
  what lies outside the org (moved repositories, sibling orgs, sites with no public source).

Docs site: fetch `<site>/llms.txt`, confirm each listed page has a Markdown twin (a `.md` URL,
or a `?surface=` variant), and derive the `urls` regex, the `prefix` and a floor below today's
page count.

Done when every candidate has a verdict and a reason.

## 3. Config entry

Add the source to `config/upstream-docs.json`; the file is checked strictly and the existing
entries are the schema.

- `github`: `owner`; per repository `ref` (its default branch; an archived repository is frozen
  on it), `license`, and `paths` entries with `path` (one file, or a glob with its own `floor`
  and optional `exclude`) and `when` (the task the page serves; `find` matches on it).
  `.html` and `.rst` are converted to Markdown, `.mdx` stays; `"convert": false` keeps a file
  verbatim. A rule package (a loader file plus operational files): mirror those, exclude its
  CONTRIB and `*.contrib.md` files.
- `llms`: `index`, `urls`, `prefix`, `floor`. `docs-json`: `index`, `raw`, `pages`, `floor`.
- `notes`: `Enforcers`, `Outside the org`, `Skipped` with reasons. They render into the
  source's `MIRROR-INDEX.md`, so the next survey starts from them.

Done when `python3 -m unittest discover -s scripts/tests -p 'test_sync_upstream.py'` passes;
it validates the real config.

## 4. Sync

`python3 scripts/upstream/sync-upstream.py <source>` (GitHub API through `GH_TOKEN` or
`gh auth token`; pandoc for conversions). Each WARN names a missing or failed file; an ERROR
means the floor failed and the previous copy stayed. Fix the entry and rerun. Done when the
run prints `done: ok=<n>` with the count you expected.

## 5. Verify and hand over

- `python3 skills/upstream-docs/query.py find <a term from a when label>` lists the new pages;
  `outline` one large page shows its headings.
- `python3 -m unittest discover -s scripts/tests` and `bash scripts/healthcheck.sh` pass.
- Report in chat: pages mirrored per repository, the skipped candidates with their reasons,
  licenses worth a look. The config entry and its `notes` are the record; nothing hand-written
  goes under `docs/upstream/`.
- Commit per the `small-commits` skill, then run the `ship-pr` skill.

Known from the Google and Facebook surveys: an org may have no style-guide repository at all,
with guides inside project repositories, one file each; default branches vary (`master`,
`gh-pages`, `static_h`); large repositories return truncated trees; a guide's format changes
upstream (HTML to Markdown), and the weekly report shows that drift, so following a branch beats
pinning.
