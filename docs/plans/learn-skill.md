# Learning a new subject: design record

Working record of the `grilling` interview started 2026-11-10. In progress: resume at the first
open question below. Once built, fold it into `docs/how-it-works.md` and delete this file.

## Requirements (user)

- **R1.** A skill or agent helps the user learn a new subject, and the learning gets faster.
- **R2.** The worked example is PostgreSQL, in three steps: set up the environment (pgAdmin 4,
  how to use the GUI); understand the basic concepts, with an index map of the whole subject;
  then advanced topics such as migrating a database.
- **R3.** Two jobs, restated by the user at Q3 (2026-11-10): **ask** anything about the subject
  being learned, and get a **map**, the whole index of the subject at a glance. R1's "faster"
  is measured against those two jobs, not against lessons.

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

- **D3. Ask takes five kinds of question, each with its own answer shape.** Every answer
  lands on a map node.
  - Concept or theory ("what is MVCC"): a plain explanation, one small example, the node.
  - Tool or GUI how-to ("restore a backup in pgAdmin 4"): numbered click path from the tool's
    official docs for the user's version, what should show after each step; the user may
    paste a screenshot when stuck, since the agent cannot see the screen.
  - Command or error ("`deadlock detected`", "write this join"): the exact command or query,
    run here to show real output when the tool can be installed, else marked untested.
  - Comparison or choice ("pg_dump or pg_upgrade"): a short table, then a recommendation for
    the user's case.
  - Navigation ("what next", "where does VACUUM fit"): from the map, the node, what it needs
    and what it unlocks.

  Why: the user asks about theory and about the tools' GUI alike (Q4a); a click path and an
  explanation need different shapes. Not chosen: concept and GUI only (errors, comparisons
  and "what next" left without a shape); one shape for all (GUI answers turn into prose).

- **D4. A follow-up matched to the kind, and no lessons.** Concept: one short recall question
  in the user's own words. GUI how-to: "do it now and tell me what you see". Command or error:
  a small variant to run. Comparison and navigation: none. The user may ignore any follow-up.
  Why: an answer only read fades within days; recall or doing is what makes it stick, and
  doing a GUI step is stronger practice than recalling it (Q4). Not chosen: one recall line
  for every kind (weak for GUI steps); no follow-up (nothing shows what stuck); `teach`'s
  lessons and quizzes (the multi-session course R3 moved away from).

- **D5. The map is an index only; it holds no progress.** No per-node state (learned, shaky,
  asked); an answer and its follow-up never mark the map. Why: the user wants the map as a
  plain index of the subject (Q5). Consequences: a navigation answer ("what next") works from
  the map's order and prerequisites and from what the user says they know, not from recorded
  progress; the 1d/3d/7d ladder has no weak items to take, so it is out unless asked for
  again (to confirm at the end). Not chosen: the tool marks state itself, asks before
  marking, or the user marks by hand.

- **D6. A question off the map adds its topic to the map.** The tool answers, adds the
  missing topic under the right stage and says so in one line ("Added *Connection pooling*
  under Stage 2, Performance"). The map only gains topics; it still tracks no progress (D5).
  Why: an off-map question shows the index was incomplete, and the map's job is the whole
  index (Q6). Not chosen: suggest and wait for a yes (one more reply each time); a fixed map
  rebuilt only on request (asked topics never reach the index).

## Open questions

Reworked after R3: the tree is now map plus ask, and lessons are out (D4).
Asked in this order; each depends on the ones above it.

1. The ask reply (Q7, asked)'s limits: `tutor`'s one claim and nine sentences per reply, or freer.
2. The map: format, node contents, size, where it lives, handed over or built together.
3. Where the map's and the answers' facts come from and how far they are trusted.
4. Stage 0: what "environment ready" means and who does the installing.
5. Shape: a new skill, `tutor` extended, `teach` reworked, or an agent.
6. The 1d/3d/7d ladder: out after D5; confirm at the end.
7. What is measured to know the learning got faster.
8. The four CLIs: what is shared and what is a documented native difference.
