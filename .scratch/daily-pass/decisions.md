# Daily-log pass: grilling state

Status: interview finished; decisions 1-14 confirmed by the owner (2026-11-02). Next:
`/to-spec`, `/to-tickets`, or "go" for the build on this branch (`feat/daily-pass`).

Feature: the journal's work entries are written once a day by one pass over the day's
evidence, one entry per project; the per-turn Stop nudge and its hooks go away.

## The entry (owner's sample in Nov/week-2, 2026-11-02)

```
- [X] <project>: <what the day was about>
	- keyword: <1-3 lowercase tags, comma-separated>
	- description: <one line, about 160 chars: what exists now and its state>
```

No `next:`, no counts, no hashes. Box always `[X]`.

## Why (what the Stop nudge produced on 2026-11-02)

- 7 sessions on ai-dotfiles, 4 edited files, 3 logged: 4 labels for one project (design /
  build / ai_dotfiles / verify flow), 7 bullets on one entry, `next:` trails. The merge key
  was the whole label; the nudge text asked for "what changed, what is next".

## Facts found during the interview

- Session stores. Claude: `~/.claude/projects/<cwd-slug>/<session>.jsonl`, lines carry `cwd`,
  UTC `timestamp`, `gitBranch`; `ai-title` entries hold a generated title, `last-prompt` the
  last prompt; assistant text blocks; about 1 MB a session. Codex:
  `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl`, `session_meta.payload` has `cwd`,
  `timestamp`, `originator` (`codex-tui` | `codex_exec`); `response_item.payload.type ==
  "message"` with `role`. Pi: `~/.pi/agent/sessions/<cwd-slug>/<ts>_<id>.jsonl`, line 1 is
  `{type: session, cwd, timestamp}`, then `message` entries with `role`. Antigravity:
  `~/.gemini/antigravity-{cli,ide}/brain/<id>/.system_generated/logs/transcript.jsonl`,
  `USER_INPUT` / `PLANNER_RESPONSE`, no cwd.
- Timestamps are UTC; the owner is at UTC+8 (CST).
- Today's 4 Codex rollouts were `codex exec` probes in /tmp and /private/var/folders.
- A resumed session's file spans days: pick messages by timestamp, not files by date.
- SessionEnd cannot write: Claude 1.5 s budget and no decision control; Codex 1 s default,
  3 s max; Antigravity has none (claude/hooks.md, codex/hooks.md, antigravity/hooks.md).
- `claude -p "/<skill>"` runs a skill from the prompt (claude/headless.md:230); `--model`,
  `--allowedTools`, `--max-turns`, `--permission-mode` exist (claude/cli-reference.md).
- `claude` is `~/.local/bin/claude -> ~/.local/share/claude/versions/<v>`: the plist needs the
  absolute path, rendered at install; `config/` stays free of machine paths.
- learning-tutor's `vendor/daily_log.py` already differs from the skill's script (line 16,
  the agent_hooks import from 7d8fea5); its drift check fails today.
- launchd runs a missed StartCalendarInterval job at wake, not for a day the Mac was off.

## Decisions

1. Trigger: a daily pass. Not Stop (one turn of one session), not SessionEnd (no model,
   tiny budget, Antigravity lacks it), not git commit (commit on request only, design work
   stays uncommitted).
2. Hooks: removed, not kept as a recorder. The pass reconstructs the day.
3. Evidence: Claude, Codex and Pi sessions of the day, grouped by cwd; temp cwds dropped
   (/tmp, /private/var/folders, the Claude scratchpad dirs); per group that day's git log and
   reflog and the current status. Antigravity: unsupported, documented (no cwd in its
   transcript). No scan of repos without sessions.
4. Day cutoff: 04:00 local; messages 00:00-04:00 belong to the previous day. A pass-only
   rule; the grammar is unchanged.
5. Run: every morning about 07:30 for yesterday, then the 3 days before it that still have
   evidence without an entry. On demand any time: `daily-log day [--date D]`.
6. Write policy: fill gaps only; an existing entry, hand or machine, is never touched;
   `--rewrite` redoes a day on purpose.
7. Runner: a launchd LaunchAgent running `claude -p "/daily-log day --date yesterday"` with a
   cheaper model (sonnet) and a tool allowlist: the evidence command, Read, `daily-log add`.
   ai-dotfiles installs the plist (a new installer step); the healthcheck checks it is loaded.
8. `keyword:` 1-3 lowercase tags, comma-separated; reuse first: the pass greps this and last
   month's `keyword:` lines before coining a tag. No list file.
9. `description:` one line, about 160 chars, telegraphic: what exists now and its state
   (merged, installed, uncommitted, in review). No `next:`, no counts, no hashes.
10. Layout: `scripts/agent_sessions.py`, the CLIs' session stores behind one interface, like
    agent_hooks.py; `skills/daily-log/scripts/day_pass.py`, evidence and the gap guard;
    `daily-log day` dispatches to it. `daily_log.py` returns to a one-file writer with no
    agent_hooks import; the tutor's vendor copy is refreshed.
11. Project key: the model names the project from the content (`ai-dotfiles`, `CS vault`);
    the script derives nothing from the folder or the remote.
12. Gap check: the model sees the day's existing block beside the evidence and writes only
    uncovered work, never rewriting. Guard in `daily-log add`: refuse a second entry whose
    prefix equals an existing one after lowercasing and dropping `_`, `-` and spaces;
    `--rewrite` lifts it.
13. Migration: hooks.py keeps the old daily-log mark in a retired list and strips those
    entries on the next install (as skills.py does for a retired Pi extension); the Pi
    extension drops its daily-log half; the state folder is deleted; worktree-guard's hooks stay.
14. Today's block: collapsed by hand into one entry in this session.

## Defaults (not asked; change on request)

- Chat-only sessions are in the evidence with their titles; the model drops what is not work
  ("a question answered in chat is not work").
- The pass prompt lives in `skills/daily-log/SKILL.md` (a Day pass section). `day_pass.py`
  prints one evidence pack per cwd group: session titles, user prompts, the last assistant
  text per turn (truncated), edited files, git facts; capped per session.
- `--session` on `daily-log add` and the `hook` subcommand go; `--if-absent` stays.
- Docs: LOG-FORMAT.md work entry v2; SKILL.md; the daily-logger README trigger table (the
  Stop-hook row becomes the pass); how-it-works.md; install.sh header (sixth step).
- Tests: HookTest removed; agent_sessions and day_pass on fixture transcripts; the hooks.py
  retired mark; the launchd step (dry-run, uninstall, idempotent, backup, refuse foreign).

## Open risks

- Headless `claude -p` at 07:30 needs a logged-in CLI and a Mac that is awake or asleep, not
  off; an off day is caught up by the 3-day window.
- Session stores are not stable interfaces (Codex says so); each reader fails soft per file.
- The vendor refresh is a change in another repo (learning-tutor, uncommitted tree).
