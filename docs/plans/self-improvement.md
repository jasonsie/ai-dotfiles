# Self-improvement inside ai-dotfiles ($0)

Status: active

## Goal

A low-budget way for this setup to improve itself, borrowing ideas from Harness²
(`sieener/harness2`): find what goes wrong in agent sessions, make the smallest fix
(skill, script, project rule, or nothing), and keep only fixes with evidence.

## Decisions

1. **Budget: $0 extra.** Everything runs inside the existing CLI subscriptions. No Google
   Cloud and no Harness² runs; a paid step needs a new decision.
2. **Trigger: on demand, after a bad session.** The user runs the review when an agent
   clearly went wrong; nothing runs automatically.
3. **Evidence: the current session.** The review runs in the session that went wrong, so
   the conversation is already in context; no transcript readers, same in all four CLIs.
4. **Action: propose, then write after approval.** Changes to ai-dotfiles go on a branch.
5. **Finding ai-dotfiles from another project:** resolve the skill's own folder link
   (each CLI's skill folder links to `ai_dotfiles/skills/<name>`), so no machine path is
   written into the repo. Settled by checking the live links, not asked.
6. **Allowed targets:** project `AGENTS.md`; a new or edited skill in ai-dotfiles (helper
   scripts inside the skill folder); global `AGENTS.md` only for a rule true in every
   repository and every CLI (rare); hooks, plugins or subagent files only as a last resort.
7. **CLI-only fixes (hooks, plugins, subagents):** only after text in a skill or
   `AGENTS.md` was clearly ignored again; kept in that CLI's native place, labelled with
   the CLI it works in, never copied or faked for the other CLIs.
8. **Proof: retry + repeat rule.** Where possible, retry the failed step in the same
   session with the fix applied. A project rule may land after one case; a skill or global
   change needs the same problem seen at least twice.
9. **Problem log: one file in ai-dotfiles** (e.g. `docs/lessons.md`), one short row per
   problem: date, project, cue, smallest fix, status. The repository is private (checked:
   `jasonsie/ai-dotfiles`); rows describe the pattern, not project secrets.
10. **Scope: only the self-improvement / self-learning loop** (review skill, problem log,
    lessons reaching later sessions). The repo guards from Harness² (skill checks, size
    limit, `skills.lock` evidence field) are out of scope; the user is interested in
    self-improvement, not repository checks.
11. **Lessons reach later sessions by log + promotion.** The review skill reads
    `docs/lessons.md` first to spot repeats; a repeated pattern is promoted into a skill or
    a project `AGENTS.md`, which every CLI already loads. Chosen as the option closest to
    a self-learning mechanism: it closes the loop (observe → log → repeat → promote →
    later sessions behave differently) without loading the log into every session.
12. **Trigger: hooks + model decision** (replaces decision 2). A hook marks a possible
    learning moment; a model decides whether it is one and, if so, starts the review
    (decision 4 still applies: propose, write after approval). Hooks here are the
    mechanism's trigger, not a fix, so decision 7's "last resort" rule does not apply to
    them; each CLI still uses its native form, labelled, never faked.

    Facts checked in `upstream/docs/` (2026-10-20):

    | CLI | End-of-turn event | Can continue the session | Model-run hook types |
    |---|---|---|---|
    | Claude Code | `Stop` (after every reply) | `decision: "block"` + `reason`, or `additionalContext`; guard `stop_hook_active`, cap 8 | `prompt`, `agent` (small background model) |
    | Codex | `Stop` | `decision: "block"`: `reason` becomes a new user prompt; guard `stop_hook_active` | none (`prompt`/`agent` parsed but skipped) |
    | Antigravity | `Stop` (`hooks.json`) | `decision: "continue"`: `reason` injected as a system message | none (`command` only) |
    | Pi | no hooks; extensions (TypeScript) | `agent_before_settle` / `turn_end` return `continue: true` | none |

    So the common form in all four is a command hook (a Pi extension) that asks the
    session's own model to decide. Claude Code alone could also let a small model decide.
13. **The hook asks the model at two moments only:** (a) when a plan is done, i.e. a
    `docs/plans/*.md` file changes to status `done` in this session (end-of-turn hook);
    (b) when the user's prompt contains a learning keyword (prompt-time hook).

    Prompt-time hooks checked (2026-10-20): Claude Code and Codex `UserPromptSubmit`
    receive the prompt and can add `additionalContext`; Antigravity `PreInvocation` gets
    no prompt text, only `transcriptPath`, and can inject an `ephemeralMessage`; Pi's
    `before_agent_start` exposes the prompt and can add a message.
14. **Keywords: explicit learning phrases plus strong corrections, in English and
    Chinese**, e.g. "learn from this", "remember this", "don't do that again", "you
    forgot", "not what I asked", "記住", "下次", "又錯了". Kept in one editable file in the
    skill folder. A false alarm costs one short model check.
15. **The session's own model decides.** The hook only hands it a short instruction
    ("decide whether this was a learning moment; if yes, run the review; if no, say so in
    one line and stop"). Reason: it has the whole conversation (decision 3) and the same
    path works in all four CLIs. Cost: one extra turn on the normal model per check.
    Claude Code's small `prompt` hook model is not used.
16. **Install: a new `scripts/install-hooks.py`.** Hook scripts live inside the review
    skill's folder (`skills/<name>/hooks/`). The installer merges one tagged entry per
    event into each CLI's global hook file and links the Pi extension; it previews by
    default, backs up, rolls back, and removes only entries it created. Added to
    `install.sh` and `healthcheck.sh`. The script's absolute path goes only into the live
    config, never into the repo. Not via `managed.json` (it sets whole keys and would wipe
    the user's own hooks) and not as plugins (three formats, Codex trust review).

    Global hook locations checked (2026-10-20): Claude Code `hooks` in
    `~/.claude/settings.json`; Codex `~/.codex/hooks.json`; Antigravity
    `~/.gemini/config/hooks.json` (its `/hooks` command writes there); Pi
    `~/.pi/agent/extensions/*.ts`.
17. **Loop safety: our own per-session record, once per plan.** The hook script keeps a
    small state file per session ID outside the repo (e.g.
    `~/.local/state/ai-dotfiles/learn/<session>.json`) listing the plans it already asked
    about. It never asks twice about one plan and never asks during a continuation it
    started (`stop_hook_active` in Claude Code and Codex; its own marker in Antigravity and
    Pi, which have no guard). Hard cap: 3 asks per session. State files older than 7 days
    are deleted by the script. The prompt-time hook only adds context, so it cannot loop.
18. **"Plan done" detection: snapshot at the first prompt, compare at end of turn.** The
    prompt-time hook records every `docs/plans/*.md` status in the session's state file on
    its first run; the end-of-turn hook re-reads them, and a plan that was not `done` (or
    did not exist) and now is triggers the ask. Status is read loosely, because plan files
    differ (`Status: active`, `Status: **done** (2026-10-18). …`): the first line starting
    `Status:`, `**` ignored, first word `done`. Not git (misses mid-session commits) and
    not a text rule (the model can ignore it, which is why decision 12 chose hooks).
19. **Skill text: our own, inspired by Harness².** Short plain text built on these
    decisions (session evidence, log, promotion, propose then approve), with a one-line
    credit to Harness². No LICENSE or `skills.lock` pin; Harness²'s prompts target
    automated benchmark runs, so most of their text would not apply.
20. **Skill name: `learn`** (`skills/learn/`, run by hooks or by typing `/learn`). Its
    description must say it reviews the agent's setup after a session, not that it teaches
    a topic, so it is not confused with `query`. No clash in the live skill folders
    (checked 2026-10-21: `grilling`, `query`, `synced`).
21. **`docs/lessons.md`: one table row per pattern, updated on repeats.** Columns
    `Cue | Lesson | Seen | Fix | Status`. `Seen` lists dates and project names (e.g.
    `2026-10-21 ai_dotfiles; 2026-10-25 shop-api`), so decision 8's repeat count is
    visible at a glance. Status: `watching`, `proposed`, `promoted: <target>`,
    `dropped: <reason>`. Keeps the file short enough to read in full on every review.
22. **Proof: tests, then a live smoke test in each CLI.** Unit tests for
    `install-hooks.py` (preview, idempotent, backup, refuse, rollback) and for the hook
    script with sample hook input per CLI (keywords, status parsing, snapshot comparison,
    loop guard, 3-ask cap); `healthcheck.sh` checks the hook entries. Then, in a scratch
    repo in each of the four CLIs: flipping a plan to `done` asks exactly once, and typing
    "remember this" asks. A CLI that fails is documented as unsupported, never faked.

## Plan vs mechanism

This file is the **plan**: the one-time work of building the loop; it ends with status
`done`. The **mechanism** is what stays in the repo afterwards and keeps learning on its
own: the review skill, `docs/lessons.md`, and the promotion step. Decisions are judged by
how well the mechanism runs without this plan.

## Build notes (2026-10-21)

- Hooks run `python3` from PATH, not an absolute interpreter: the hook script is
  stdlib-only and works on macOS `/usr/bin/python3` (3.9), and the command stays the same
  whichever Python ran the installer, so Codex does not ask for trust again.
- Every hook command ends in `|| true`, and the script exits 0 on bad arguments: an
  exit code of 2 would block every prompt in Claude Code and become a prompt at Codex's
  `Stop`.
- Ownership is marked by the hook command (it runs `skills/learn/hooks/learn_hook.py`)
  and, for Pi, by the link target; no receipt file was needed.
- Pi: the context message uses `before_agent_start`; the end-of-turn ask uses
  `agent_before_settle` with a `custom_message` entry (a bare `continue: true` is dropped).

## Done and changed files

Branch `feat/learn`, committed 2026-10-21 and rebased onto `origin/main` (`fd8142c`); not pushed.

- New: `skills/learn/` (`SKILL.md`, `keywords.txt`, `hooks/learn_hook.py`,
  `hooks/pi-learn.ts`), `scripts/install-hooks.py`, `tests/test_install_hooks.py`,
  `tests/test_learn_hook.py`, `docs/lessons.md`.
- Edited: `scripts/install.sh` (step 6, hooks), `scripts/healthcheck.sh` (hooks section),
  `AGENTS.md` (map row, six steps), `docs/how-it-works.md` (flow line, self-improvement
  section), this file.
- Applied on this Mac: `bash scripts/install.sh --apply` linked the `learn` skill and wrote
  the hooks into `~/.claude/settings.json`, `~/.codex/hooks.json`,
  `~/.gemini/config/hooks.json`, and `~/.pi/agent/extensions/ai-dotfiles-learn.ts`
  (backup under `~/.local/state/ai-dotfiles/settings/`).

## Checks run

- 2026-10-21 re-check: `bash scripts/install.sh` preview reports 0 changes in all six
  steps; `bash scripts/healthcheck.sh` reports healthy.
- 2026-10-21 clean reinstall test: everything the installer applied was removed (links,
  hooks, managed keys, context7, vault via `--uninstall`); backup in
  `~/.local/state/ai-dotfiles/cleanup-20261021-122228`, to delete once the user confirms
  the reinstall. The preview then listed every step as pending (knowledge skipped until
  `ZKFY_DIR`/`ZKFY_VAULT` are set). The user reinstalls next.
- `python3 -m unittest discover -s tests`: 77 tests OK.
- `shellcheck scripts/install.sh scripts/healthcheck.sh`: clean. (`sync-cli-docs.sh` has
  an SC2016 info note that predates this work.)
- `bash scripts/healthcheck.sh`: healthy, including the new hooks section.
- Live smoke tests in a scratch git repo (headless):

  | CLI | Prompt cue | Plan turned `done` |
  |---|---|---|
  | Claude Code (`claude -p`) | pass: the model quoted the note | pass: asked once, model answered in one line |
  | Pi (`pi -p`) | pass | pass: asked once, guard cleared |
  | Antigravity (`agy -p`) | pass (prompt read from the transcript) | pass: asked once, guard cleared |
  | Codex | not run: needs one-time trust in `/hooks` | not run |

  Pi's `--mode json` printed nothing for 60 s and was killed, also with
  `--no-extensions`, so the hang is Pi's own, not the extension's; text mode works.
- The "yes, a lesson" path (`claude -p`, Read/Skill/Bash only, a correction with "remember
  this"): the model ran `learn`, found `docs/lessons.md` in this repo through the skill
  link, applied the repeat rule (first logged case, so `watching`), proposed one row,
  and asked before writing; `docs/lessons.md` stayed unchanged (checksum before and after).

## Next step

1. The user approves the two Codex hooks once with `/hooks`, then runs both smoke tests
   in Codex (a prompt with "remember this"; a plan flipped to `done`). If Codex fails,
   document it here as unsupported (decision 22).
2. The user reviews, pushes, and opens the PR for `feat/learn` (merges before `feat/install-cli`).
3. Mark this plan `done`; the mechanism then runs on its own.
