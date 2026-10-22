---
name: learn
description: Review the agent's own setup after a mistake or a finished plan in this session (rules, skills, hooks), log the lesson, and propose the smallest fix so later sessions behave better. Use when a hook reports a learning cue or a plan marked done, or when the user says "learn from this", "remember this", or "/learn". Not for learning a topic; for knowledge questions use `query`.
---

Turn what went wrong in this session into the smallest lasting fix, and only keep
fixes with evidence. The session itself is the evidence: you have the conversation in
context, so do not go looking for transcripts.

## 1. Find the lesson log

The log is `lessons.md` in this skill's own folder; resolve its real path (for example
`realpath` on the folder this file is in), which lies in the ai-dotfiles repository. If
it does not exist yet, there are no earlier lessons; create it with the header from Log
format when you log the first one. Read it in full before deciding anything: a cue that
is already listed is a repeat.

## 2. Look at this session

Name, in one line each:

- **Cue:** the observable sign of the problem (what the user said or what failed).
- **Lesson:** what the agent should have done instead, stated so it applies beyond
  this one task. If it only fits this task, there is no lesson; say so and stop.
- **Fix:** the smallest change that would have prevented it, from the first target
  that fits:
  1. nothing (a one-off slip, or already covered by an existing rule that was ignored once);
  2. the project's `AGENTS.md` (a rule for this repository only);
  3. a skill in ai-dotfiles, new or edited (helper scripts go inside the skill folder);
  4. the global `config/global-agents.md` (only for a rule true in every repository
     and every CLI; keep it short, with no `@` imports or HTML comments);
  5. a hook, plugin, or subagent file, only when text in a skill or `AGENTS.md` was
     already ignored again. Use the CLI's native place, label which CLI it works in, and
     never copy or fake it for the other CLIs.

## 3. Apply the repeat rule

- A project rule may land after one case.
- A skill or global change needs the same cue seen at least twice (two entries in
  `Seen`). The first time, log it as `watching` and propose nothing larger.
- Write the pattern, not project secrets: no credentials, client names, or code.

## 4. Propose, then wait

Show the user the log row and the exact change (file and text). Write nothing until
they approve. After approval:

- Update `lessons.md`: add a row, or add today's date and project to `Seen` on the
  matching row, and set the status.
- Make ai-dotfiles changes on a branch, not on `main`; commit only when the user asks.
- Where possible, retry the step that failed with the fix in place, and report whether
  it now works.

## Log format

`lessons.md` starts with a `# Lessons` heading and holds one table row per pattern:

| Cue | Lesson | Seen | Fix | Status |
|---|---|---|---|---|
| short sign | what to do instead | `2026-10-21 project-a; 2026-10-25 project-b` | target file | status |

Status is one of `watching` (seen, no fix yet), `proposed`, `promoted: <target>`, or
`dropped: <reason>`.

Inspired by the reflection step of Harness² (Google, Apache-2.0); written for this setup.
