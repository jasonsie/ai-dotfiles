# Daily log format

The grammar of the daily logger, one journal for hand-written entries, the `daily-log`
command, and the learning-tutor engine. Every writer follows it; the engine's parser
reads by it.

## Files

- Root: `--root`, else `$DAILY_LOGGER_ROOT`, else `~/Documents/Claude/Projects/daily-logger`.
- Week file: `<root>/<yyyy>/<Mon>/week-<i>`, no extension. `Mon` is the calendar
  abbreviation (`Oct`); `i` is the index of the week holding the day in
  `calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)` of the **day's own
  month**. Oct 1 lives in `Oct/week-1`, Sep 29 in `Sep/week-5`, even though a hand-made
  `Sep/week-5` can also carry a `# 10/1` block. Weeks start on Monday.
- A week file opens with the header section and closes each day block with the 84-dash
  separator. The weekly report region (`# Week of <Monday> — <Subject>` between
  `<!-- weekly-report:start -->` and `<!-- weekly-report:end -->`) sits in the header,
  under `# Thought`.

```
# Week Goal
------------
# Thought

------------------------------------------------------------------------------------


# 10/26 (Mon)
------------
- [] leetcode
	- [ ] 72-Edit Distance(new)
	- [ ] 981-Time Based Key-Value Store(weak)

- [X] /onboard skill
	- docs/onboarding.md written
	- starter AGENTS.md


------------------------------------------------------------------------------------
```

## Day block

- Heading `# M/D (Dow)` (no zero padding, `Mon`…`Sun`), then a 12-dash rule, then the
  entries, blank lines, and the separator. A new day block is appended at the end of the
  file after the last separator; a generated file already holds every day's heading.
- Entries are separated by one blank line. A new entry goes under the block's last
  content line; the first entry sits directly under the rule.

## Entry

- Label line, top level: `- [X] <label>` done, `- [] <label>` open. The label is free
  text (`leetcode`, `/onboard skill`, `ai-dotfiles: daily-log hook`).
- Sub-bullets: one TAB, then `- ` (`	- tests green`). Notes under a sub-bullet: two
  TABs, then `↳ ` (`		↳ O(n)/O(1) — hash set`). TABs, never spaces.
- Same day and same label is one entry: a second write merges, drops lines already
  present, and may flip the box to `[X]`; it never un-checks it or rewrites other lines.

## Study item line

The learning-tutor's sub-bullet. One line per item, written blacked out, read back as the
outcome contract:

```
	- [ ] 678-Valid Parenthesis String(new)
	- [x] 76-Minimum Window Substring(solved)
	- [~] 84-Largest Rectangle in Histogram(weak)
	- [tutored] 875-Koko Eating Bananas(weak)
	- [x] 543-Diameter of Binary Tree(weak) -Trees -[[cs.d.0.7.Trees]]
		↳ O(n)/O(h) — postorder heights
```

- Shape: `<id>-<title>(<kind>)`. `id` is numeric: the LeetCode number for the `dsa` key,
  the curriculum `order` for every other key. `kind` is `new`, `weak` or `solved`
  (`review` and `resolve` are legacy, read but never written).
- Box, the 4-valued outcome the learner fills in: `[ ]` untouched, `[x]` clean,
  `[~]` shaky or needed help, `[tutored]` solved only with the tutor.
- Reveal, written the next morning on attempted lines only: ` -<Topic_Tag>` (spaces as
  `_`), then ` -[[<vault link>]]` when the key has a concepts table, then the note line
  `		↳ <target complexity or definition>`. Untouched lines keep their blackout.
- After-note, the deeper form of the same line: the header gains `: <pattern name>`
  before the tag, and four note lines follow, `↳ why:`, `↳ def:`, `↳ recognize:`,
  `↳ next:`, terse fragments, one line each.

## Parser-inert lines

Anything that is not an indented `- [<mark>] <digits>-…(<kind>)` line under a study
label is ignored by the engine: free-form sub-bullets, the weekly report, hand entries.
Keep report and recap lines out of that shape.
