---
name: daily-log
description: Record what was done in the daily logger (the journal at ~/Documents/Claude/Projects/daily-logger) in its house grammar, through the `daily-log` command. Use when the user says "log it" or "add this to the daily", asks what was done today, or runs the day pass (`/daily-log day`, the morning job that writes yesterday's entries from the CLIs' sessions); also the output rules every <subject>-tutor-daily task follows.
---

# Daily log

One work entry per project per day, written once by the day pass (below) or by hand when
the user says "log it". A question answered in chat is not work.

```
daily-log add --done "<project>: <what the day was about>" "keyword: <tags>" "description: <one line>"
```

- Label: the project as the user names it (`ai-dotfiles`, `CS vault`, `moodlens_web`), a colon,
  what the day was about in a few words.
- `keyword:` one to three lowercase tags, comma-separated; reuse a tag the journal already
  has before coining one.
- `description:` one line, about 160 characters, telegraphic: what exists now and its
  state (merged, installed, uncommitted, in review). No `next:`, no counts, no hashes.
- The same label merges; another label for a project already in the block is refused:
  `--rewrite` replaces that entry instead. `--open` for work in progress, `--date` for
  another day, `--if-absent` to touch nothing when the label exists. `daily-log show` prints
  today's block, `daily-log path` its file.

The command is `~/.local/bin/daily-log`, linked by ai-dotfiles; without the link, run
`python3 ~/.claude/skills/daily-log/scripts/daily_log.py`.

## Grammar

[LOG-FORMAT.md](LOG-FORMAT.md): files, day blocks, entries, the study item line. Every
writer follows it; the learning-tutor engine writes its day block through this command.

## Day pass

Each morning at 07:30 a LaunchAgent (installed by ai-dotfiles) runs
`claude -p "/daily-log day"`, which lands here. Do this:

1. Run `daily-log day`. It prints, for yesterday and the three days before it, each day
   with sessions: the day's existing block, the keywords in use, then one group per
   working folder with its repository's facts (commits, reflog, uncommitted files) and
   its sessions (CLI, span, title, what was asked and answered, files edited). A day runs
   from 04:00 to 04:00. Sessions come from Claude Code, Codex and Pi; Antigravity's
   transcripts name no folder and are not read.
2. For each day, decide the projects from the content, not the folder: the folder
   `ai_dotfiles` is the project `ai-dotfiles`, the Obsidian vault is `CS vault`, one folder
   may hold two projects, two folders one. Skip chat-only sessions and probes in temp
   folders. Skip every project the existing block already covers, whatever its label;
   never change an existing entry. With `rewrite: on` in the output, pass `--rewrite` and
   replace instead.
3. Write one entry per uncovered project with the command the output ends with (`--date`
   set to that day), in the shape above. Prefer the day's commits and the sessions' last
   replies for the state. Write nothing for a day with nothing uncovered.
4. Reply with the entries written, one line each, or "nothing to add".

Run it by hand any time: `daily-log day --date today`, `daily-log day --date 2026-11-02
--back 0 --rewrite`.

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
