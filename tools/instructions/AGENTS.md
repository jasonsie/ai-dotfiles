## Task memory

In a git repository, track multi-session tasks in `docs/plans/<task>.md` (unless
the repo says otherwise): status (`active` or `done`), goal, decisions, changed
files, checks run, and next step. Read active task files when starting; update
them before stopping. Outside a git repository, skip this.

## Subagents

Hand bounded work (search, reading, summaries, mechanical edits, checks) to
subagents on a cheaper, faster model when the CLI allows it. Keep the strongest
model for planning, design, review, and hard debugging. Verify subagent results.
