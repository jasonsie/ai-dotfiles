# Shared global instructions

These personal defaults apply to Claude Code, Gemini CLI, Codex CLI, and Pi.
The source of truth is `ai-cli-workspace/tools/instructions/AGENTS.md`; the
four user-level instruction files are links to this file. Keep it CLI-neutral.
Repository instructions provide the project-specific workflow; do not treat the
workspace library's maintainer instructions as rules for unrelated repositories.

## Communication

- Reply in English when the user uses English. For Chinese, use Taiwan Traditional Chinese.
- Be concise. Before nontrivial implementation, state your understanding and key
  assumptions; ask when ambiguity materially changes the work.
- During longer tasks, report completed work, the current step, and blockers.
  Distinguish planned work from changes actually made and checks actually run.

## Implementation and verification

- Read the relevant project instructions and existing code before editing.
- Prefer small, focused changes that follow the project's language and style.
  Preserve unrelated edits, user-owned configuration, and existing behavior.
- Run the smallest relevant tests or lint first. Report failures and any checks
  you could not run; do not present generated configuration as runtime-verified.
- Follow the project's Git workflow. Stage only intended files, not `git add -A`.
  Use clear commit messages such as `fix: ...`, `feat: ...`, or `docs: ...`.
  For a PR, summarize the whole branch (`git diff <base>...HEAD`) and include a test plan.
- Do not expose credentials or broaden permissions to make a task succeed.
  Back up existing configuration before a migration.

## Context and tools

- Keep globally loaded context small. Load detailed rules and reference material
  only when relevant; keep repository facts and transient task state local.
- Use the current CLI's available tools. Do not assume Claude-specific commands,
  model names, hooks, or subagents exist in Gemini or Codex.
- If delegation is supported and useful, give independent tasks bounded context
  and return summaries. Otherwise work directly and state the limitation.
- Before compaction or a handoff, preserve the goal, decisions, changed paths,
  validation results, and next step. Treat stale memory as suspect and verify it
  against current files; do not turn observations into permanent rules unasked.

## Read-only knowledge retrieval

Before substantive architecture, harness design, implementation tradeoffs,
debugging explanations, or learning guidance, consult the configured CS vault.
This includes advisory tasks; skip trivial edits, greetings, and unrelated work.

Read the shared procedure using the current CLI's file-reading tool: Pi uses
`~/.pi/agent/skills/vault-query/SKILL.md` (respect `PI_CODING_AGENT_DIR`);
other CLIs use `~/.claude/skills/vault-query/SKILL.md` (respect
`CLAUDE_CONFIG_DIR`). The procedure is CLI-neutral. Then use
`~/.local/bin/vault-knowledge search "focused concepts" --limit 6` and the
launcher's `read` command on supporting sections. Cover distinct facets with
focused queries, not broad filesystem searches. Cite only sections actually read
and distinguish recorded claims from synthesis, contradictions, and gaps.

Queries must not write notes, logs, or indexes, access excluded `raw/` material,
run maintenance/ingestion, or research externally. Saving knowledge requires a
separate explicit request. If the procedure, launcher, or vault is unavailable,
report that limitation and rely explicitly on current project evidence instead.
