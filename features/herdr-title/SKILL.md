---
name: herdr-title
description: "The label on an agent's row in Herdr's sidebar, such as `grill › run` or `execute › wait › ask`. Use when the user asks what a label means, why one is wrong, stale or missing, or wants the types, the words or what decides them changed."
---

# Herdr title

Inside a Herdr pane, a hook labels the agent's row in the sidebar with three layers,
**type › status › result**: `execute › wait › ask`. The hook in
[scripts/herdr_title.py](scripts/herdr_title.py) keeps one **mode** per session and reports one
label for each state Herdr detects; the session's agent does nothing for it. The types, the
words, the rules that decide at once and both model instructions are
[labels.json](labels.json), the single source for every answer below.

```text
◐ herdr-title-hooks               the tab's name
  execute › wait › ask            the label: type › status › result
  AI-Config · claude              the space, then the CLI
```

## Read a label

- **type**: what the user's prompt is for, one of ten (`types` in the config). Left out while
  the session has none yet: `run`, `wait › ask`.
- **status**: whose move it is. `run` is the agent's: working, its own background agents still
  at work, or the ~3 s while a stop is judged. `wait` is the user's. `idle` is nobody's: no
  task, or a finished job the user has looked at.
- **result**, only under wait: `ask` (answer it, in the reply or a dialog), `allow` (a
  permission dialog), `fail` (an error or a usage limit), `done` (finished, not looked at yet).
  No result: the hook cannot tell why it waits.
- The icon in front is Herdr's own status, not the label's: an asking row the user has looked
  at shows Herdr's idle icon. Rows that wait on an ask, a failure or a verdict that never came
  carry the pane token `need`, and the hook's agent view ("needs you") sorts them to the top.
  Codex's bare wait from a prompt to its stop hook carries none: it starts while Codex works.

## Who set it

1. **A typed prompt**: normal mode at once (in Codex a bare `› wait` until its stop hook
   answers), reported with the type the session already has.
   A command word or a named skill (`commands`, `skills`, `outside`) sets the type at once;
   otherwise Haiku names it about 3 s later (`model.type`).
2. **A turn end**: `› wait › ask` at once when the reply's last line ends with a question mark
   or the reply ends with a Codex plan block (`ask_at_once`); `› wait › fail` at once after an
   API error, Pi's error, or Claude Code's usage-limit note (`usage_limit_note`). Otherwise
   `› run` while Haiku reads the reply's last 800 characters (`model.stop`): ASK, WAIT (kept
   only while Claude Code lists work of a `background` type or a scheduled prompt, else
   done), DONE, or no answer, which reads a bare `› wait`.
3. **A dialog**: a permission dialog reads `› wait › allow`; a question or plan dialog and an
   MCP form read `› wait › ask`, until the next prompt or turn end.
4. **A resume** (Claude Code's `--resume`, `--continue` or `/resume`; Pi started on a kept
   session, Herdr's restore included, or its `/resume`): the state kept at the session's end
   comes back. Codex has no hook for it: a resumed Codex pane waits for a typed prompt.
5. **Left as it was**: by a prompt the user did not type (`machine`, or a scheduled prompt the
   last stop listed: a `/loop` tick, a cron, a wake-up), which keeps the type and an open
   ask through the turn it starts, while a failure gives way to that turn; by a subagent's calls,
   except its permission dialogs; by every call from another session, since a pane belongs to
   the session the user last typed into there (a teammate in Claude Code's agent-team tmux
   server and a headless `claude -p` started from the pane never own it).

The labels and the `need` token come off when the session ends; its state stays, pruned after
a week.

## A label is wrong or stale

Name which case above produced it, then fix that case's source: the wording of `model.type`,
`model.stop` or a type's meaning for a wrong model pick; a missing entry in `commands`,
`skills`, `outside` or `machine`; the `ask_at_once` marks; the `background` types. Some events
fire no hook and leave the label as it was: Esc in Claude Code, a question dialog closed
without an answer (both end the turn, Herdr shows idle), and a dialog no hook announces later
in the same turn, which keeps the earlier dialog's word. A Stop hook that keeps Claude Code going
after a question (`/goal`) leaves `wait › ask` while it works. A session's state is
`~/.local/state/ai-dotfiles/herdr-title/<session>.json` (type, mode, blocked); `panes/` holds
each pane's owner (`$HERDR_TITLE_STATE` moves the folder).

Known limits, not bugs:

- Haiku's turn-end verdict was right on 91% of 191 real turn endings; its mistakes lean to
  calling a finished job an ask.
- Codex has no error event, so a failed Codex turn reads as done.
- A scheduled prompt is known by the text the last stop listed for it, read off transcripts and
  not seen at the hook; an autonomous `/loop` (given no prompt) fires with other text, so it
  likely reads as typed.
- Herdr keeps no labels across a restart of its server. A resumed Claude Code or Pi session
  reports its kept state again; a Codex pane waits for its next typed prompt.

## A label is missing

Check in this order: the session runs outside a Herdr pane; the CLI is Antigravity, which has
no hook for a submitted prompt; the hooks are not installed (`ai-dotfiles install --dry-run`
lists what is pending) or Codex's are not approved in `/hooks` (until then a Codex stop reads a
bare `› wait`); Herdr's sidebar rows lack `state_text` (set up below); the session has had
no typed prompt since it started; the session is a tmux teammate or a headless run, which
never label a pane. A label that shows but never gets its type, or whose turn end stays
`› run`, may lack `claude`: every session, Codex's and Pi's included, asks Haiku through a
headless `claude -p`, as the daily pass does.

## Draw the label in the sidebar

Once per Mac, by hand: Herdr owns `~/.config/herdr/config.toml`, and its default rows show no
label. Set `status_indicators` in the `[ui]` table and replace the `rows` key in
`[ui.sidebar.agents]`; add a table only if the file lacks it, since TOML refuses one declared
twice. Then run `herdr server reload-config`:

```toml
[ui]
status_indicators = "symbols"

[ui.sidebar.agents]
rows = [
  ["state_icon", { token = "tab", fg = "#abb2bf", bold = true }],
  [{ token = "state_text", rules = [{ contains = "› done", fg = "#98c379" }, { contains = "idle", fg = "#98c379" }, { contains = "wait", fg = "#e06c75", bold = true }, { contains = "run", fg = "#e5c07b" }, { contains = "working", fg = "#e5c07b" }] }],
  ["machine", "workspace", "agent"],
]
```

Row 1 is the icon and the tab's name, row 2 the label, row 3 the space and the CLI. The rules
color the label by whose move it is, in three colors: red for the user's (`ask`, `allow`,
`fail`, a bare `wait`), yellow for the agent's (`run`), green for nobody's (`done`, `idle`).
The `› done` rule stands before `wait`, since a done label holds both words. The colors are the
one-dark theme's. Without these lines the labels are reported and not drawn; a row nothing has
labeled shows Herdr's own word, `idle` or `working`, in the same green and yellow. Three rows
per agent fit about 3 agents at the default split in a 27-row window; drag the divider between
spaces and agents for more.

## Change the types, the words or what decides them

Edit `labels.json` in the ai-dotfiles repo, in a worktree of its own;
`tests/test_herdr_title.py` checks the file, every label within 22 columns included. The
color rules in the user's Herdr config (above) repeat the label's words (`› done`, `wait`, `run`...): a
renamed word changes both places. The hook reads the config on every call, so a change is live once the main checkout
has it.
