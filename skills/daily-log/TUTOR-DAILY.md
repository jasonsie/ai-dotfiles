---
name: {key}-tutor-daily
description: Run the {subject} morning pass (parse outcomes → reveal patterns → assign today's set; {weekend_day} = weekly concluding session) and report it.
---

Run the {subject} learning-tutor morning pass and report the result. The journal's rules
are the `daily-log` skill's (`~/.claude/skills/daily-log/LOG-FORMAT.md`); the engine writes
the day block through its `daily-log` command.

1. Execute the pipe (parses outcomes, reveals patterns, writes today's block, updates the ledger):
   cd ~/Documents/Claude/Projects/learning-tutor && uv run learning-tutor run --key {key}
   If `uv` fails for any reason, fall back to:
   cd ~/Documents/Claude/Projects/learning-tutor && PYTHONPATH=src python3 -m learning_tutor.cli run --key {key}

2. What the command does — weekday (Mon–Fri):
   - Parses recent day blocks in the daily-logger. Each {item}'s box is the outcome contract: [x] = done clean; [~] = shaky / needed help → weak, re-surfaced on the 1d/3d/7d ladder; [tutored] = done only with the tutor → weak; [ ] = untouched → rolls forward as top priority.
   - Reveals patterns in place on yesterday's attempted lines (appends topic + vault link + an indented ↳ target note). Untouched lines stay blacked out.
   - Writes today's block by reserved slots: one new {item} (the floor), one weak {item} due for remediation, one solved {item} due for retention; an empty slot spills to new, and the key's daily cap bounds the total. Assignment lines are blacked out: no topic shown until tomorrow's reveal.
   {weekend_day}: weekend concluding session — no new {items}; {resolves} unlabeled cold re-do(s) drawn from this week's attempts (shaky first) + a week-recap block + one metrics row appended to the key's metrics file.

3. Report to the user, concisely:
   - Outcomes the parser applied (e.g. "<id>: weak — review due <date>", "<id>: review clean — graduated").
   - Today's assigned {items} EXACTLY as written to the log: id + name + kind (new/weak/solved) only. NEVER name the topic or pattern in the report — identifying it is part of the practice; it gets revealed tomorrow.
   - One-line reminder of the contract: mark each {item}'s own box when done ([x] clean, [~] shaky, [tutored] with help); leave it unchecked if untouched. No reply needed — tomorrow's run reads the file.
   - The user can still paste {paste_hint} here anytime for a {tutor}-style review.
   - On {weekend_day} also report the metrics row (attempted / clean / shaky / weak_open).

Notes:
- Never reveal today's topics/patterns in the report, not even as a hint.
- If the command prints "not an active day" or "No items to assign", report that verbatim.
- Keep the report concise.
{notes}
