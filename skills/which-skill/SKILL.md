---
name: which-skill
description: Ask which skill or flow fits your situation. A router over the skills this repository installs.
disable-model-invocation: true
---

# Which skill

You don't remember every skill, so ask. Before stating what a skill does or recommending
that a step be skipped, read that skill's `SKILL.md`: the summaries here are for
orientation only.

A **flow** is a path through the skills. Most work travels one **main flow**; four
**on-ramps** merge onto it. Everything else is standalone, repository setup, or a
vocabulary layer that runs underneath.

## Main flow: idea → ship

1. **`grill-with-docs`** sharpens the idea by interview, one question at a time, and
   records terms in `GLOSSARY.md` and decisions as ADRs. Use it whenever a repository is
   under you. Without one, use **`grilling`**: the same interview, leaving no docs.
2. **Can every question be settled in conversation?** If one needs a runnable answer (a
   state model, business logic, a UI you have to see), detour: **`handoff`** out,
   **`prototype`** the answer in its own directory, **`handoff`** back what you learned.
3. **A multi-session build?**
   - **Yes:** **`to-spec`** turns the thread into a spec on the issue tracker, and
     **`to-tickets`** splits it into tracer-bullet tickets with blocking edges. Work them
     with **`implement`**, one ticket per fresh session, or **`implement-spec`** for the
     whole spec on one integration branch, with sub-agents across the ready frontier.
   - **No:** **`implement`** here, in this session.

   Either way the code is built with **`tdd`** (red, then green, one slice at a time) and
   reviewed with **`spec-review`** on two separate axes, Standards and Spec. Each also
   works on its own. When the work goes up as a pull request, **`pr`** writes the body.
4. **`retro`** closes the loop: it looks back over the session and suggests changes to
   the environment (checks, coding standards, navigation pointers, steering files), not
   to the code.

Keep steps 1 to 3 in one context window until `to-tickets` is done, so the spec and the
tickets build on the same thinking; each `implement` then starts fresh from its ticket.

## On-ramps

- **New to a repository** → **`onboard`** writes `docs/onboarding.md` (goal, tech
  stack, folder structure, layer map and workflow graphs, conventions, common tasks,
  where to look) and a starter `AGENTS.md` when the repo has none, then asks for a
  folder, layer or workflow to dive into, or a task.
- **Bugs and requests piling up** → **`triage`** turns incoming issues into agent-ready
  briefs for `implement`. Only for issues you didn't write: `to-tickets` output is ready.
- **Something's broken** → **`diagnosing-bugs`** builds a tight feedback loop first, then
  fixes with a regression test. Afterwards, `retro` asks what would have prevented the
  bug; a missing seam is a job for `improve-codebase-architecture`.
- **Too big for one session** (a greenfield project, a huge feature) → **`wayfinder`**
  maps the open decisions as tickets on the tracker and resolves them one at a time. It
  decides, it doesn't build: once the way is clear, join the main flow at `to-spec`.

## Codebase health

- **`improve-codebase-architecture`** surveys the code for deepening opportunities and
  writes an HTML report; the candidate you pick is an idea for `grill-with-docs`.

## Vocabulary underneath

Model-invoked references the skills above pull in. Reach for one directly when the words,
not the process, are the problem.

- **`domain-modeling`**: the project's domain language (`GLOSSARY.md`) and its ADRs.
- **`codebase-design`**: the deep-module vocabulary (module, interface, depth, seam,
  adapter) for designing a module's shape.
- **`writing-for-agents`**: writing anything an agent reads: skills, `AGENTS.md`, docs
  reached by a pointer.

## Phase boundaries

Between two phases of work (grilling, building, review), choose in this order: continue;
clear the context; **`handoff`** when the work moves to another CLI, folder or person; a
sub-agent for a tightly scoped task; compact. [PHASE-BOUNDARIES.md](PHASE-BOUNDARIES.md)
has the reasoning and each CLI's commands.

## Standalone

- **`grilling`**: the interview by itself. `grill-with-docs`, `triage`, `wayfinder` and
  `improve-codebase-architecture` run it inside.
- **`research`**: a background agent reads primary sources and leaves one cited
  Markdown file, to take into `grill-with-docs`.
- **`to-questionnaire`**: the answer is in someone else's head; it writes them a
  questionnaire to fill in.
- **`wizard`**: steps only a human can take (credentials, a third-party dashboard, a
  one-off migration) as an interactive bash script.
- **`herdr`**: inside a Herdr pane, drive Herdr (split panes, run commands, start, prompt
  and wait on other agents) by loading the skill the installed `herdr` prints; in a
  flow-on repo each agent it spawns makes its own worktree.
- **`herdr-title`**: the label on each agent's row in Herdr's sidebar, type › status ›
  result (`execute › run`, `execute › wait › ask`), set by a hook at each prompt, turn end and
  dialog; the skill explains a label that is wrong or missing and where the words are listed.
- **`wait-what`**: the last message didn't land; the agent re-pitches it plainly.
- **`teach`**: learn a concept over several sessions in a workspace folder.
- **`tutor`**: one question about one source, taught in four moves (locate, gap, build,
  check) in plain words; reads a `teach` workspace and today's day block when in reach,
  writes nothing.
- **`house-style`**: learn the company's document style from a sample: one template per
  document type, global, with per-project deltas; every CLI then writes documents in it.
- **`upstream-docs`**: look a rule up in the mirrored Google and Meta style guides,
  Google's code review guide, the docs-writing guides and the Claude Code, Codex, Pi and
  Antigravity docs: find a page, outline it, show one section.
- **`collect-docs`**: add a source to that mirror: survey an org, repository or docs site,
  write its entry in `config/upstream-docs.json`, sync and index it.
- **`portable-plugin`**: a plugin that runs in Claude Code, Codex, Pi and Antigravity from one
  repo: the rules its files follow, the check and the release; ai-dotfiles installs each
  plugin in `config/plugins.json` at its pin.
- **`daily-log`**: record finished work in the daily logger through the `daily-log`
  command; its grammar is what the learning-tutor and every `<subject>-tutor-daily`
  task write; its hook nudges a session that changed files but logged nothing.
- **`worktree-guard`**: in a repo switched on, each task works in its own worktree and
  an edit in the main checkout or another session's worktree is refused; the skill is how
  a session names its work, and `ai-dotfiles worktree` lists, archives and removes
  those worktrees.
- **`small-commits`**: commit the way the hook accepts: under 300 changed lines, one
  concern, `type(scope): outcome` and the Why:, Scope:, Verified: trailers; the plan to
  show first, how to split, and what a block means.
- **`approve`**: once the user has reviewed a branch and said "approve": commit, PR body,
  then `ai-dotfiles approve` runs the git steps below in order, resumable. "approve <n>":
  `ai-dotfiles approve <n>` lands PR n from any session, nothing local. Either form, run in
  the work's own worktree, deletes that worktree last: only the archive tag is left.
- **`ship`**: the agent's finish in a worktree `worktree new` made: `ai-dotfiles ship` runs the
  repo's checks, pushes the work as `<type>/<slug>`, opens the PR, deletes the worktree.
- The git steps, each alone as `ai-dotfiles git <step>`: **`push-branch`** (to origin),
  **`open-pr`** (open or reuse), **`approve-pr`** (approve as the repo's cached reviewer
  account), **`archive-tag`** (`archive/<name>` at the tip before a branch goes; also
  worktree-guard's), **`merge-pr`** (merge commit), **`prune-branch`** (branch deleted
  locally and on origin; run in a linked worktree, the worktree too).

## Repository setup

- **`setup-agent-skills`**: run once per repository before the main flow: issue tracker,
  triage labels, domain-doc layout.
- **`setup-pre-commit`**: Husky and lint-staged with formatting, type checks and tests
  on every commit.
- **`migrate-to-shoehorn`**: replace type assertions in tests with
  @total-typescript/shoehorn.

Adapted from `ask-matt` in mattpocock/skills (MIT License; see LICENSE here).
