# One-run install, update, uninstall, global command

Status: done (2026-10-21). Merged to `main` as #20 (#18 had merged into `feat/learn`); `ai-dotfiles check` healthy.

## Goal

User feedback on the install flow:

1. One run installs (no separate preview run, then `--apply` run).
2. An uninstall script.
3. An `--update` flag.
4. After the first run from the repo root, a command is available from every directory.

## Facts checked

- `scripts/install.sh` previews unless `--apply`; each of its 6 Python steps has its own `--apply`.
- Repo `CLAUDE.md` rule: "Every installer previews by default …" (decision 1 changes it).
- Only `install-vault-knowledge.py` has `--uninstall`; other steps keep backups under
  `~/.local/state/ai-dotfiles/` (instructions, settings, mcp) or a receipt (`skills.json`).
- `~/.local/bin` is on `PATH`; `~/.zshrc` holds hand-written aliases.

## Decisions

1. **A plain run writes; `--dry-run` previews.** (User chose this over preview-then-confirm.)
   Backups, idempotency, refusal to overwrite foreign files, and rollback stay. The
   `CLAUDE.md` rule "previews by default" changes to match; docs and README follow.
2. **All installers flip, not only `install.sh`.** The 6 step scripts (`install-global-
   instructions.py`, `apply-settings.py`, `apply-mcp.py`, `install-vault-knowledge.py`,
   `install-skills.py`, `install-hooks.py`) write by default and take `--dry-run`. One rule
   everywhere. (User chose this over flipping only `install.sh`.) `--apply` is removed, not
   kept as a no-op (my call: no cruft; an unknown flag fails loudly). Files to update: those
   6 scripts, their tests (`test_global_instructions`, `test_install_hooks`,
   `test_install_skills`, `test_knowledge_adapter`), `README.md`, `docs/how-it-works.md`,
   repo `CLAUDE.md` rule; ADR-0006 gets no edit (history), a new ADR records the change.
3. **One global command `ai-dotfiles` with subcommands**, a thin wrapper `scripts/ai-dotfiles`:
   `install` (default) → `install.sh`; `update` → `install.sh --update`; `uninstall` →
   `scripts/uninstall.sh`; `check` → `healthcheck.sh`. Flags (`--dry-run`, `--target=`) pass
   through; `--help` lists the subcommands. (User chose this over putting `install.sh` on
   PATH or several commands.)
4. **Global via a link `~/.local/bin/ai-dotfiles` → `<repo>/scripts/ai-dotfiles`**, created by
   `install.sh`, recorded in a receipt so uninstall removes only that link. The wrapper
   resolves its link to find the repo (no machine path in the repo). If `~/.local/bin` is not
   on `PATH`, print a hint; never edit shell rc files. A moved repo breaks the link until
   `install.sh` reruns; `check` reports it. (User chose this over a `~/.zshrc` alias.)
5. **`update` = pull this repo, then rerun the install.** `git pull --ff-only`, print the
   incoming commits, then the normal install. Refuses (no stash, merge, or branch switch)
   when the tree is dirty or the branch is not `main`. Does not upgrade the CLIs and does
   not touch `upstream/` (the weekly workflow owns that). (User chose this over also
   upgrading CLIs or refreshing mirrors.)
6. **`uninstall` removes everything that points into this repo; plain config values stay.**
   Removes: instruction links (and restores the pre-install file recorded in the earliest
   backup manifest, if one existed), skill links (`skills.json`), learn hook entries and the
   Pi extension link (by marker), vault binding (existing `--uninstall`), and finally the
   `~/.local/bin/ai-dotfiles` link. Leaves settings keys and MCP servers (no record of prior
   values; they do not depend on the repo) and prints them for manual removal. Test: after
   uninstall, deleting the repo breaks nothing. (User chose this over receipts for settings
   and MCP or removing by name.)
   My calls: uninstall follows decision 1 (writes by default, `--dry-run` previews, backs
   up first); it takes `--target=`; each step gets an uninstall mode in its own script
   (as `install-vault-knowledge.py --uninstall` already does), and `uninstall.sh` runs them
   in reverse install order. `healthcheck.sh` also checks the global link.

7. **Git: commit the learn work on `feat/learn` first, then branch `feat/install-cli` from
   it.** One PR each; `feat/learn` merges first. The user's "1" authorized the `feat/learn`
   commit; the Codex smoke test from `self-improvement.md` can still follow it.
   My call: `update` pulls, then `exec`s the freshly pulled `install.sh` (bash reads a
   script as it runs, so the old copy must not continue after the pull).

## Done and changed files

User confirmed ("go", plus: pull the latest changes). `feat/learn` committed and rebased
onto `origin/main` (`fd8142c`); local `main` fast-forwarded; `feat/install-cli` branched.

- New: `scripts/ai-dotfiles` (wrapper), `scripts/install-command.py` (step 7),
  `scripts/uninstall.sh`, `tests/test_install_command.py`, `tests/test_entrypoints.py`,
  `docs/adr/0007-one-run-install.md`.
- Edited: all six step scripts (`--dry-run`; `--uninstall` for instructions, skills, hooks;
  settings and MCP `--uninstall` only list leftovers), `scripts/install.sh` (`--update`,
  step 7), `scripts/healthcheck.sh` (command section), `README.md`, `docs/how-it-works.md`,
  `AGENTS.md`, tests for skills, hooks, instructions.
- Hooks and instructions uninstall modes written by Sonnet subagents, reviewed here.

- Uninstall also skips stale instruction originals: empty, only tool-written
  `<!-- x:start/end -->` blocks, or only an `@` import of a file now gone. Found on this
  Mac's Oct 5 backups (Claude dead import, Antigravity empty, Pi old zkfy block); the user
  chose to skip the Pi block rather than restore it.

## Checks run

- 2026-10-21: `python3 -m unittest discover -s tests` 125 OK (124 also in a fresh clone);
  shellcheck clean except the SC2016 info in `sync-cli-docs.sh`, already on `main`.
- `install.sh --dry-run` on this Mac: 0 changes in every step except 18 skill links (the
  6 onboarding skills merged on `main` via #15, × 3 folders) + receipt, and the command link.
- `uninstall.sh --dry-run` on this Mac: removes hooks, skill links, vault binding,
  instruction links (restores none); lists context7 and the managed keys.

## Next step

Done on 2026-10-21: first real `install.sh` run (one run; `ai-dotfiles` linked);
`ai-dotfiles check` from `/tmp` → healthy. PRs: #17 (`feat/learn`) then #18 (this branch).
Remaining: the user merges #17, then #18; mark this plan `done` after the merge.
