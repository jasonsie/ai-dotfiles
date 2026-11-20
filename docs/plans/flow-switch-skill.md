# Flow switch as a skill

Turning the worktree flow on or off in a repo becomes a skill the person invokes, instead
of a command the person types (`ai-dotfiles worktree on|off`). A design in progress; folded
into `docs/how-it-works.md` and deleted once built. Builds on
[worktree-convention.md](worktree-convention.md) (P1, P1b).

## Decisions

- **S1. The person invokes; the agent switches.** A user-only skill (`disable-model-invocation`):
  the person's typing it is the consent, and the agent runs the switch. P1b becomes "only the
  person asks for it": the guard still refuses an agent's own `worktree on|off`, and lets one
  through when the person invoked the skill. Rejected: a skill that only prints the command for
  the person to run (still a CLI step); dropping P1b (an agent blocked by "name this work" could
  turn the flow off).

- **S2. A Mac dialog is the person's yes.** The switch asks "Turn the worktree flow off in
  <repo>?" in a macOS dialog and changes nothing until the person clicks OK. Same in all four
  CLIs; an agent cannot click it, nor can a prompt the person did not type (Herdr lets one agent
  type into another's pane). The guard stops refusing `on|off`: the dialog is the gate. Rejected:
  a prompt hook that arms a one-time pass (Antigravity has no prompt event; a Herdr-sent prompt
  looks typed); both (two mechanisms for one gate).

- **S3. The skill is the only door.** `on|off` leave `ai-dotfiles worktree`; a skill of its own
  (worktree-guard is model-invoked, S1 needs user-only) owns a small script that imports the
  guard's flow code. `worktree list` still shows `flow: on|off`. Rejected: keeping the command
  beside the skill (the CLI step the person wanted gone).

- **S4. `/worktree-flow` is a toggle, no arguments.** It flips the repo's flow; a repo starts
  off (no setting is off). The dialog names the direction ("Turn the worktree flow on in
  <repo>?"), so a toggle from the wrong belief is caught before it lands. Rejected: `on|off`
  arguments; two skills (`/worktree-on`, `/worktree-off`).

## Assumed

- Cancel, a dialog that cannot open (no GUI) or one left unanswered (gives up after a while):
  nothing changes, and the skill says why.
- Antigravity may load the skill on its own (no explicit-only setting); harmless, the dialog
  still gates it.
- Cloud sessions cannot run it (no Mac): a reason in `config/cloud.json`.
- Messages that say "`worktree on` is the fix" point to `/worktree-flow`; issue #69's
  acceptance line likewise.
- `PERSON_ONLY` keeps `release` and `share`; the tests that refuse `worktree on|off` from an agent
  become tests that the command no longer exists and that Cancel changes nothing.
