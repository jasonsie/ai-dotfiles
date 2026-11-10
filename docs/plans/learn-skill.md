# Learning a new subject: design record

Working record of the `grilling` interview started 2026-11-10. In progress: resume at the first
open question below. Once built, fold it into `docs/how-it-works.md` and delete this file.

## Requirements (user)

- **R1.** A skill or agent helps the user learn a new subject, and the learning gets faster.
- **R2.** The worked example is PostgreSQL, in three steps: set up the environment (pgAdmin 4,
  how to use the GUI); understand the basic concepts, with an index map of the whole subject;
  then advanced topics such as migrating a database.

## Facts, 2026-11-10

- `skills/teach` (pinned from mattpocock/skills at `5beb35b`, one local edit) keeps a multi-session
  workspace: `MISSION.md`, one short HTML lesson at a time, learning records, reference sheets.
  It picks the next lesson from the mission and the learning records. It has no map of the
  whole subject, no setup stage and no stages from basic to advanced.
- `skills/tutor` (own) answers one question about one source in four moves. It reads a `teach`
  workspace when one is in reach and writes nothing.
- The `learning-tutor` engine (outside this repo) and `daily-log tutor-daily` re-surface weak
  items on a 1d/3d/7d ladder from the journal. They need items to exist; nothing makes them
  for a new subject.
- So retention and question answering are covered. Nothing covers R2's three steps.
- `teach` picks the next lesson in one place (`skills/teach/SKILL.md:85-89`). It differs from
  its pin by two lines, and upstream `main` matches the pin today, so every line changed in
  `teach` becomes a `local_edits` entry to re-apply on each upstream bump.
- `tutor` reads `MISSION.md` and the last three learning records (`skills/tutor/SKILL.md:31`),
  not `reference/`. A Markdown file at the workspace root is the one place both can read.
- A study line for the 1d/3d/7d ladder needs a whole-number id. The engine's config and
  curriculum format live outside this repo and were not read.
- 45 skills: 17 user-invoked, 28 model-invoked. Tests bind a skill's frontmatter
  (`test_skills.py`) and require `which-skill` to name it (`test_which_skill.py`); 654 tests
  pass here in 49 s.

## Decisions

- **D1. Map first, with setup as stage 0.** The skill's first output is an index map of the
  whole subject, staged setup, then core concepts, then advanced. Every lesson hangs off a node
  of the map. Why: the time is lost not knowing what the subject contains or in what order
  (user, Q1). Cost accepted: one research-heavy session before any learning. Not chosen:
  hands-on first (no view of progress or of what is skipped), retention first (the engine does
  it already), task first (holes in the fundamentals).

- **D2. Any technical subject; stage 0 is optional.** A map has a setup stage only when the
  subject has a tool to install or run (PostgreSQL, Docker). A theory subject (statistics,
  system design) starts at core concepts. Why: the user wants theory subjects covered too
  (Q2). Cost accepted: the skill needs a rule for when to skip stage 0, and "ready" is checked
  by a command only when there is one. Not chosen: tool subjects only (too narrow); any
  subject at all (`teach` already does that, and setup and hands-on tasks become vague).

## Open questions

Asked in this order; each depends on the ones above it.

1. Its shape (Q3, asked): a new skill beside `teach`, a rework of `teach`, or an agent.
2. The map: format, node contents, size, where it lives, handed over or built together.
3. Where the map's facts come from and how far they are trusted.
4. Stage 0: what "environment ready" means and who does the installing.
5. Progress: per-node state, who marks it, and the link to the 1d/3d/7d ladder.
6. Stage 2: how an advanced topic such as a migration is taught.
7. What is measured to know the learning got faster.
8. The four CLIs: what is shared and what is a documented native difference.
