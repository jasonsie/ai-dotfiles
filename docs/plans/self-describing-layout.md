# A repo that speaks for itself: design record

Working record of the `grilling` interview of 2026-11-20, held after an `/onboard` pass over
this repo. D1 to D6 are settled with the user, except rule 2 of D3, which is open again (see
Open). Nothing is built yet: the user asked for this record to ship first, and what follows
waits for the user's signal (see Next). Once built, this file is deleted (D6).

## Terms

A **feature** here is a program that runs inside a session or beside it: worktree-guard,
small-commits, herdr-title, the git flow (ship, approve and the six git steps), daily-log, the
status line and the cloud session. The code already uses the word (`Feature` in
`scripts/install/hooks.py`, `features` in `scripts/agent_hooks.ts`); the glossary in
`docs/how-it-works.md` does not. A **unit** is one thing this repo sets up or tunes: a CLI, a
plugin, a skill, a feature.

## Requirements (user)

Each is the user's, said on 2026-11-20; a reading after it is the agent's.

- **R1. The codebase speaks for itself.** The user's stated main purpose. Reading: a reader
  learns the design from the tree and the code, not from a map kept in the docs. Later the
  user asked for it to be readable "with no extra doc or note".
- **R2. Single truth.** "we should also keep the single truth principle". Reading: each fact
  has one home; nothing restates it.
- **R3. Config is what sets things up.** "we use config to 'set up'".
- **R4. Further refactoring is welcome.** "we could refactor further".
- **R5. A stale doc is removed, not preserved.** "if we are talking about the doc. eager to
  'rm' the stale one instead of preserve" (on where the last hand-written lines should live).

## Facts, 2026-11-20

Measured on `main` at a56c583, and checked again at bcea534 by two independent checkers per
claim. Timings are medians of 21 runs on one Mac.

- **One feature, many homes.** herdr-title sits in 9 places (12 tracked files) across four
  top-level folders and the root: code and skill text (`skills/herdr-title/`), the skill index
  (`skills/which-skill/SKILL.md`), words (`config/herdr-title.json`), hook list
  (`scripts/install/hooks.py`), Pi's list (`scripts/agent_hooks.ts`), cloud note
  (`config/cloud.json`), tests (`scripts/tests/`, 2 files), design (`docs/how-it-works.md`),
  map rows (`AGENTS.md`, `README.md`). worktree-guard is named in 32 files.
- **Hook wiring is written in three executable places,** each for a different target:
  `*_WANTS` in `scripts/install/hooks.py` (three features; Claude Code, Codex, Antigravity),
  `features` in `scripts/agent_hooks.ts` (the same three, for Pi), and `.claude/settings.json`
  (small-commits alone, for Claude Code in a cloud session). Each timeout is written in
  seconds in the first and in milliseconds in the second; small-commits' is in the third too.
  Tests check the first and the third; none checks Pi's.
- **Docs restate, and rot.** Seven facts (install steps, subcommands, hook events, CLI paths,
  cloud lists, state folders, skill counts) are restated in well over 100 places (one count
  said 151; it depends on what counts). At least 12 are stale (recounts found 17 to 22): "five
  steps" (7), "37 skills" (47), "both hooked features" (3), zkfy 1.8.1 (the pin is 1.9.1), a
  README line that has `ai-dotfiles worktree` "merge" worktrees, a verb it lacks.
- **No visible dependency graph.** 19 `sys.path.insert` sites in Python files outside tests.
  `skills/git` and `skills/worktree-guard` import each other; `scripts/` and its `install/` too.
- **Shell-command reading exists three times in two files, and the readers differ.**
  `worktree_guard.py` has `git_changes` and `guard_calls`; `small_commits.py` has `tokens_of`
  with `commits_in`. Only `guard_calls` strips heredocs and breaks at a newline. Issues #82 and
  #48 are each a bug in one reader: #82 is `git_changes` lacking that strip, #48 is `tokens_of`
  falling back to `command.split()` on an unclosed quote. A probe confirms `git_changes` and
  `commits_in` each count `git commit` inside heredoc text as a command.
- **`worktree_guard.py` is 1,388 lines** in nine sections: process table, git plumbing, what a
  tool call changes (shell reading included), steering, claims, hook routing, linked worktrees
  (records, removal, command handlers and creation: 470 lines, the largest), Claude's native
  hooks, and the command parser with its eleven `worktree` commands.
- **Two kinds under one name.** `skills/` holds what runs and what agents read: of 47 skills,
  12 front a feature's code, 3 carry a small tool of their own (`onboard`, `upstream-docs`,
  `collect-docs`), 2 a shell template (`diagnosing-bugs`, `wizard`) and 30 are Markdown only.
  `scripts/` is as mixed: entry points, the cloud setup, the seven install steps, CLI adapters,
  two features (the status line, the cloud session), the docs-sync scripts and every test.
- **A hook call takes about 210 ms** on this Mac, about 150 ms of it the pyenv shim that
  `python3` resolves to; the interpreter itself starts in about 15 ms. An agent's Bash tool
  call starts two hooks (worktree-guard's, small-commits') side by side, so the wait is about
  225 ms, not their sum. One Python process serving both, started from a bash script, takes
  about 220 ms: no faster to wait for, but one process, not two; started past the shim, about
  60 ms. Going through the `ai-dotfiles` command adds about 10 ms.
- **Pure file moves count 0 lines** at small-commits' size check (`git diff -M`).
- **No recorded decision forbids a layout change.** "Logic two skills need lives in one skill
  (its `scripts/`)" is an `AGENTS.md` rule with no stated reason.

## Config units, 2026-11-20

The user asked for a bird's-eye view of every unit of configuration, then for the properties
the smallest units share. The table has one row per kind of unit, its last column the
smallest piece of that kind. No decision rests on it: its question was set aside (see D3).

| Unit | Count | Written today in | Smallest piece |
|---|---|---|---|
| CLI | 4 | `config/ai-clis.json`; its formats in about 15 code files outside tests | a path (5 per CLI, of 6 kinds), a tool name, a hook event |
| Global rules | 1 file | `config/global-agents.md` | a rule section (3) |
| Managed setting | 15 keys | `config/cli-settings.json` | key, value, `enforce` or `default` |
| MCP server | 1 | `config/mcp-servers.json` | the server |
| Plugin | 2 | `config/plugins.json` | the plugin |
| Skill | 47 | its folder, plus `skills/skills.lock` (29), `config/cloud.json` (14), `config/herdr-title.json` (34), `agents/openai.yaml` (34) | the skill |
| Feature | 7 | code: no config file lists the features. Config holds parts of three: `config/herdr-title.json`, the `statusLine` keys in `config/cli-settings.json`, `config/cloud.json` with `.claude/settings.json` | a hook entry (30: Claude Code 13, Codex 8, Antigravity 2, Pi 7), a command (`ai-dotfiles`: 10 commands, with 7 `git` steps and 11 `worktree` commands under them; `daily-log`), a scheduled job (1), a tunable |
| Label vocabulary | 1 | `config/herdr-title.json` | a type (10), a word (7), the separator |
| Docs source | 6 | `config/upstream-docs.json` | a page or a repo |
| Install step | 7 | `scripts/install.sh` | the step |
| The repo's own | 5 files | `.claude/settings.json` (2 cloud hooks), the Verify block of `AGENTS.md` (4 commands, read by `ship`), `.gitattributes`, two CI workflows (Python 3.12; the mirror sync on Mondays 01:00 UTC) | |
| Per repo, outside | 3 | git config `worktree-guard.flow` and `approve.reviewer`; `.worktreeinclude` | |

Shared properties, by kind: name, on, targets, cloud and source are each written three to five
ways. Which CLIs a unit targets: a `targets` array (MCP server, plugin), a top-level key per
CLI (settings), per-CLI dicts in code (hooks), implied "all" (skills, rules). Whether a cloud
session gets it: `config/cloud.json` (skills), `features(cloud)` in code (hooks), `--cloud`
branches in `install.sh`, `'claude' in targets` in `setup.sh` (plugins), and
`.claude/settings.json`. Only a CLI carries its own `on`; a skill is on by existing, a
feature by being named in code (`features()` in `hooks.py`; for Pi, the array in
`agent_hooks.ts`), and every other kind by being listed.

## Constraints

What a move must not break:

- `skills/daily-log/scripts/daily_log.py` imports nothing from the repo, so a copy is a
  complete writer (learning-tutor vendors one).
- `scripts/statusline.py` says it runs on any python3 (3.9+); it imports only the standard
  library, nothing from the repo.
- A skill's own tool (`facts.py`, `query.py`, `survey.py`) is run by the skill's folder path.
- `scripts/cloud/environment.sh` is pasted on claude.ai and names `scripts/cloud/setup.sh`.
- A changed hook command needs one Codex `/hooks` approval, and one `ai-dotfiles install`.
- Other work in flight: PR #91 (the flow switch as a skill; it edits `worktree_guard.py`,
  `scripts/ai-dotfiles` and how-it-works), PR #90 (herdr-title label colors, in how-it-works),
  PR #84 (refreshes `docs/onboarding.md`), issue #70 (fold the worktree design into
  how-it-works). PR #76, the weekly mirror sync, changes only `docs/upstream/`; outside D5.

## Decisions

Each names who chose. A reason marked (agent) came with the agent's recommendation.

- **D1. Move files: each feature's pieces go into one folder.** Chosen by the user, with the
  cost stated: roughly 12 to 15 small PRs (the agent's estimate), one install, one Codex
  approval. It serves R1. Docs keep rules and reasons, no lists (narrowed by D6: rules stay in
  `AGENTS.md`, reasons move to docstrings). Rejected: declaring features without moving them
  (the map in `AGENTS.md` would stay needed); fixing docs only (the scatter stays).
- **D2. Config is nested.** Proposed by the user: "we think that 1. and 2. has no conflict. We
  propose the concept of nested config." 1 and 2 were the answers offered to "Where is a
  feature's setup written down?": one file, `config/features.json`; a file in each feature's
  folder. The agent's reading: config exists at each level of the tree; the root `config/`
  sets the Mac up, a feature's own config, inside its folder, sets that feature up, and with
  R2 a fact lives at the level that owns it. Narrowed by D3: the nesting stops at features,
  and answer 1's root file is not kept.
- **D3. The baseline: four rules.** The baseline is the layout the work builds toward. The
  user asked the agent to set the user's own proposals aside and propose one that is scalable,
  maintainable and readable "with no extra doc or note", and accepted all of it; rule 2 on a
  figure since corrected (below).
  1. **One folder per feature, and it describes itself:** code, tests, the agent's manual
     (`SKILL.md`) and a `feature.json` (its hooks, command, schedule, cloud or not). The
     installer finds the folders; nothing registers them elsewhere. A folder that exists is on.
  2. **One door:** everything outside the repo calls `ai-dotfiles`, never a file inside it. A
     hook file holds one line per event (`ai-dotfiles hook pre --cli claude`), and that one
     call serves every feature in one process.
  3. **What differs between the CLIs lives in one folder,** `lib/clis/`. A test fails when a
     CLI's name appears in a feature.
  4. **The tool prints its own map; rules are tests.** `ai-dotfiles status` and `--help` print
     from the data the installer uses, so no list of what exists is written by hand. A rule a
     test can check is a test, as the skill index already is; `AGENTS.md` keeps the others.

  ```text
  config/      what you want on the Mac            (data)
  skills/      what agents read                    (Markdown; a few carry a tool)
  features/    what runs, one folder each
    small-commits/
      feature.json   hooks, command, cloud: the wiring's only home
      hook.py        what it decides
      SKILL.md       the agent's manual
      tests/
  lib/         what features share
    clis/      everything that differs between the CLIs
    shell.py   reading a shell command, once (the base for fixing #82 and #48)
    install/   the install steps, as one ordered list
  scripts/     what you type: ai-dotfiles, install.sh
  ```

  Rule 2 has known exceptions (Constraints): the pasted cloud setup names
  `scripts/cloud/setup.sh`, and a skill's own tool is run by its folder path. Whether the
  `daily-log` command, linked straight to its script today, stays a second door is left open.
  Why (agent), as the cost of a change, today then proposed: a feature with hooks, 10 files
  outside its own folder and tests (herdr-title's arrival, PR #86), then its folder, a line in
  the skill index and one in `config/cloud.json`; a hook's timeout, 2 files (3 for
  small-commits') and a test that repeats the number, then 1 line; a fifth CLI, up to 18 files
  (an estimate: 13 code files and 5 config files name a CLI in a table or a branch), then one
  config entry and `lib/clis/`; an install step, 10 places in 4 files, then a module and a
  line; shell-command reading, three readers, then one.
  Checked in the mirror: Codex records trust against a hook's hash and skips a new or changed
  hook until trusted (`docs/upstream/codex/hooks.md:69`), so a line per event that never
  changes needs one approval, where today each new or changed entry needs one. Claude Code and
  Codex run an event's hooks in parallel (`claude/hooks.md:401`, `codex/hooks.md:20`).
  Left alone: the root `config/` files, all but the one D4 moves; the skills that front no
  feature; `config/cloud.json` (no per-skill config files: that list has one home and a test);
  each CLI's native files. Also kept: no generated code committed; standard library only.
  Turned down at the choice, open again (see Open): one hook entry per feature, which the
  agent offered as the safer option, today's behavior, that "gives up the Codex and speed
  gains". Corrected after the choice: the speed gain, a Bash call going from about 460 ms to
  about 255 ms, was wrong. Both figures came from a Mac busy with other agents, and the first
  added up two hooks that run side by side. Measured again (Facts), one process is as fast to
  wait for as today's two, no faster; only the Codex gain is real. The user chose rule 2 with
  the wrong figure in front of them and has not chosen again.
  Build order, each step safe alone and called step 1 to step 5 below: (1) the door and
  `feature.json`, one install and one Codex approval; (2) `lib/`, one shell reader, features
  stop asking which CLI they are in; (3) features move into `features/`, one PR each, tests
  alongside; (4) `worktree_guard.py` splits by job; (5) `ai-dotfiles status`, rules as tests,
  the maps and the rest of how-it-works deleted (D6).
- **D4. A feature's own words live beside the feature.** Chosen by the user, the agent's
  recommendation. `config/herdr-title.json` becomes `features/herdr-title/labels.json`. The
  root `config/` holds only what belongs to the whole Mac: CLIs, rules, settings, MCP servers,
  plugins, docs sources, the cloud list. A limit that never changes stays one line in code.
  Why (agent): rule 1 of D3; the file changed in 6 commits in its first 2 days, each time with
  the feature's tests and in 5 of the 6 with its script, while small-commits'
  `WARN, WALL = 300, 600` was set once. The `AGENTS.md` rule "lists live in `config/`" becomes
  "the Mac's lists live in `config/`; a feature's own live beside it". Rejected: the root
  keeps it; limits as data too (more to validate, for values that never changed).
- **D5. PR #91 and PR #90 land first; PR #84 is closed.** PR #91 (the flow switch as a skill)
  and PR #90 (herdr-title label colors) land on the user's `approve 91` and `approve 90`, not
  yet given, before step 1 starts. Chosen by the user in two answers: first the agent's
  recommendation to land all three open PRs, PR #84 (the onboarding refresh) included; then,
  with D6, to close #84 and land the other two. Why (agent): #91 edits the usage list in
  `scripts/ai-dotfiles`, which step 1 replaces, and `worktree_guard.py`, which steps 3 and 4
  move and split; #90 edits how-it-works text that step 3 moves. Whichever lands second is
  redone by hand. Rejected: starting alongside.
- **D6. Docs are deleted, not refreshed (R5).** Chosen by the user from the agent's list, with
  the cost stated: a newcomer has no single page of reasons. Nothing is carried into a new
  doc; git history keeps what goes.
  - `docs/onboarding.md`: in the PR that ships this record, with the three lines that point
    at it (two in `AGENTS.md`, one in how-it-works). PR #84, which refreshes it, is closed at
    the user's signal. `/onboard` stays a skill for other repos.
  - `docs/plans/worktree-convention.md`, and `docs/plans/flow-switch-skill.md` once PR #91
    adds it: with issue #70, one of whose criteria is that the plan file is deleted. (The
    list the user accepted named only the first, deleted "when #91 lands", its content in
    "git history; it is built"; #70 is still open. The second file is the agent's addition.)
  - Each feature's section of `docs/how-it-works.md`: in the PR that moves the feature, its
    reasons going to the feature's docstring in the same PR.
  - The rest of `docs/how-it-works.md`: step 5, the file removed. The sections on the install
    steps go to the docstring of the step that does it, and each CLI's paths to
    `ai-dotfiles status`.
  - The map in `AGENTS.md`, README's table, the install-step lists in script headers: step 5.

  Still to do before how-it-works goes (the agent first told the user less was left: five
  principles of six already rules, every glossary term with one owner):
  - Principles: four of the six are rules in `AGENTS.md`. "Link what is read-only; merge what
    a CLI writes" is one for settings files only, and "never write through a link" has none
    (`edit` in `installer.py` refuses a symlink). Both get a rule or a docstring first.
  - Glossary: of 21 entries, 16 have one owning code file (by one reading) and get their
    definition there. Five do not (Source, Receipt, Release tag, Gap, Emitted vs verified):
    each gets a home or is dropped. `docs/agents/domain.md` then says where terms live.
  - Memory (8 lines) has no home yet.

  End state: `docs/` holds `agents/` and `upstream/`. Written by hand: README (what it is,
  install), `AGENTS.md` (the rules no test can check, verify), each `SKILL.md`, docstrings.
  No test reads `docs/onboarding.md` or `docs/how-it-works.md`. 9 files point at how-it-works:
  2 are deleted above and 7 are fixed in the PRs that remove what they point at.
  Rejected: a short how-it-works of principles and glossary; folding them into `AGENTS.md`;
  keeping `docs/onboarding.md` and regenerating it.

### Follows from D3 (chosen by the agent)

Most were listed in the closing summary; the user's reply, to ship this record and wait, did
not speak to them, and none was asked one by one. Some came after it and the user has not
seen them: no `DESIGN.md`, #70's rewording, several tickets per PR (the summary said one), the
last two items of the final bullet. All are the agent's choices, not yet the user's.

- The 12 skills that front a feature move with it, and `worktree-flow` joins them once PR #91
  lands; `skills/` keeps the other 35 (33 if the docs mirror becomes a feature: see Open).
- One call per event behaves as Pi's extension does today (`scripts/agent_hooks.ts`): features
  run in a fixed order, each sees the tool input as the one before left it, a block ends the
  chain, notes are joined, and a feature that fails is skipped.
- CLI ids stay the commands people type. No `DESIGN.md` per feature: the docstring is it.
- Issue #70 says "fold the design into how-it-works"; under D3 that text goes to the guard's
  docstring and `SKILL.md` instead, and the issue is reworded.
- Tracking follows the pattern of issue #57: a spec issue with its tickets as sub-issues,
  through `to-spec` and `to-tickets`; a PR may close one ticket or several.
- Left to each step's PR: the name of the shared folder (`lib/` here) and how features import
  it; the name of the printing command (`ai-dotfiles status` here); which CLI-specific
  behaviors a feature may still name, as a short list the rule-3 test allows; how a feature
  with several skills is laid out (the git flow has eight; the tree shows one `SKILL.md`);
  whether the door starts the interpreter itself, past the pyenv shim (Facts).

## Open

- **Rule 2's one process per event.** The user chose it (answer "1", "Yes, all of it") with
  the agent's wrong speed figure in front of them, and has not chosen again. The choice is the
  user's. The other option, one hook entry per feature as today, was offered as the safer one.
  Step 1 writes the hook lines, so this comes first.
- **A feature's skills and the cloud list.** `config/cloud.json` names 14 skills a cloud
  session leaves out; 11 sit in folders that move to `features/`, where `feature.json` also
  says "cloud or not". Whether that is one fact with two homes is not settled.
- **Whether the docs mirror is a feature.** The agent's summary made it an eighth feature
  folder (sync, report, tests, the `upstream-docs` and `collect-docs` skills), its source list
  staying in `config/`. It runs in CI, not in a session, and D4 would put its list beside it.

## Next

The user's words: "let's ship 1 and wait for my signal to do the rest". Item 1 was this record
as a docs PR that also removes `docs/onboarding.md`. The rest waits for that signal:

1. PR #84 is closed with a note that says why.
2. The user answers the open questions; rule 2's comes before the spec.
3. A spec issue and its tickets are filed, and issue #70 is reworded.
4. The user approves #91 and #90.
5. Step 1 of the build order (the door and `feature.json`) starts in a worktree of its own.
