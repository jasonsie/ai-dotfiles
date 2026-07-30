# CLAUDE.md scaffolding lives in a template file, not a rules.sh heredoc

## Context

`rules.sh` generates the repo-root `AGENTS.md`, `GEMINI.md`, and `CLAUDE.md` entry
files. `AGENTS.md`/`GEMINI.md` are built entirely from `tools/rules/*.md` via the
manifest, but `CLAUDE.md` uniquely prepends a hardcoded scaffold (the four-layer
loading framework + maintainer guide). That scaffold used to live as a heredoc
literal inside `rules.sh`, which made the generated file's own header comment
("Edit `tools/rules/*.md` instead") a lie — the scaffold text was in the script,
not in `tools/rules/`.

## Decision

Move the scaffold into `tools/templates/claude-header.md` (a real source file) and
have `rules.sh` read it. The generated header now honestly points maintainers at
that template for scaffolding and at `tools/rules/*.md` for rules.

## Considered Options

- **`tools/rules/claude-scaffold.md`** — rejected: it would sit among real rule
  files but be special-cased (deliberately absent from `manifest.yaml`, so the
  manifest-driven `_build_rules_for_target` / `_build_claude_imports` skip it),
  misleading a reader into thinking it's a rule.
- **`tools/templates/claude-header.md`** — chosen: the `templates/` location names
  its role and keeps it out of the rules namespace entirely.

## Consequences

- The `## 常駐規則` heading is still emitted by `rules.sh` (not the template),
  because it must sit directly above the `@`-import lines that
  `_build_claude_imports` appends. Keeping it in the template would leave the
  file ending on a dangling heading — invalid as a standalone document. The
  seam (scaffold → heading → imports) therefore stays assembled in the script.
- This is the one asymmetry versus `AGENTS.md`/`GEMINI.md`: `CLAUDE.md` has a
  scaffold-template + imports, the other two are pure rule concatenation.
