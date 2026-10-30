---
name: daily-log
description: Record what was done in the daily logger (the journal at ~/Documents/Claude/Projects/daily-logger) in its house grammar, through the `daily-log` command. Use when a unit of work is finished, when a Stop hook reports unlogged edits, when the user says "log it" or "add this to the daily", or asks what was done today; also the output rules every <subject>-tutor-daily task follows.
---

# Daily log

A unit of work is finished (a feature, a fix, a skill, a document), or the Stop hook's
nudge arrived: record it. A question answered in chat is not work.

```
daily-log add --done "<label>" "<line>" "<line>"
```

- `label`: the project, skill or task as Jason writes it: `/onboard skill`,
  `ai-dotfiles: daily-log hook`, `learning-tutor: system-design key`.
- Lines: up to 3, telegraphic fragments: what changed, what is next. No code.
- `--open` for work still in progress; `--session <id>` when the nudge gave one (it ends
  the nudging); the same day and label merge into one entry.
- `--date YYYY-MM-DD` for another day. `daily-log show` prints today's block,
  `daily-log path` its file.

The command is `~/.local/bin/daily-log`, linked by ai-dotfiles; without the link, run
`python3 ~/.claude/skills/daily-log/scripts/daily_log.py`.

## Grammar

[LOG-FORMAT.md](LOG-FORMAT.md): files, day blocks, entries, the study item line. Every
writer follows it; the learning-tutor engine writes its day block through this command.

## Tutor-daily tasks

A `<key>-tutor-daily` scheduled task is [TUTOR-DAILY.md](TUTOR-DAILY.md) rendered for one
learning key of `~/Documents/Claude/Projects/learning-tutor/config.toml`:

```
daily-log tutor-daily --key dsa --subject DSA --item problem --tutor leetcode-tutor \
  --paste-hint "a TypeScript solution" --note "Hards are parked (difficulty_max = medium)." \
  > ~/Documents/Claude/Scheduled/dsa-tutor-daily/SKILL.md
```

The schedule itself lives in the Cowork app (Routines, New, Local, pointing at that
folder); the file on disk only holds the prompt.

## Hook

`daily-log hook tool|stop --cli <cli>` counts the session's edits (PostToolUse) and, at
Stop, continues the turn once with the nudge above when files changed and nothing was
logged: at most twice per session, never during its own continuation. ai-dotfiles installs
it into each CLI's hook file (`scripts/install/hooks.py`); Pi, which has no hooks, loads
[hooks/daily-log.ts](hooks/daily-log.ts) as an extension. State:
`~/.local/state/ai-dotfiles/daily-log/`, one file per session, kept 7 days.
