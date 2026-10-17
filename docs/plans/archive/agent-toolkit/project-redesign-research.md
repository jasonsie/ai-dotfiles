# Agent Toolkit — source checks for the redesign

> tags: [planning, native-capabilities, upstream, skills]

Checked: 2026-10-08. Companion to the [requirements plan](project-redesign.md).
These are documentation and source-code observations, not runtime verification.
URLs on moving branches identify research sources; implementation must record
the actual imported revision and content hash before activating any component.

## Native discovery evidence

| Interface | Documented behavior and primary source | Design implication / remaining check |
|---|---|---|
| Claude Code | Personal skills use `~/.claude/skills/<name>/SKILL.md`; personal/project skill directories support symlink entries. Account-managed `synced/` content has separate ownership. [Skills](https://code.claude.com/docs/en/skills) | Install only toolkit-owned entries; detect name collisions and preserve existing account/plugin content. Verify discovery with the installed version. |
| Codex CLI | User skills use `~/.agents/skills`; skill-folder symlinks are supported. Global instructions use `$CODEX_HOME` (default `~/.codex`), where `AGENTS.override.md` takes precedence over `AGENTS.md`. [Build skills](https://learn.chatgpt.com/docs/build-skills), [Instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | Honor the configuration root and report an override that masks managed instructions. Verify discovery and avoid duplicate skill names. |
| Gemini CLI | Skills use `~/.gemini/skills` or the `~/.agents/skills` alias; the alias takes precedence at the same scope. Native activation includes consent to read the skill directory. [Skills](https://geminicli.com/docs/cli/skills/) | Account for shared discovery with other tools and preserve native activation behavior. Verify the installed version's discovery. |
| Pi | Native `SKILL.md` discovery includes `~/.agents/skills`; metadata loads before full instructions, and `/skill:name` can invoke a skill. Same-name collisions warn and keep the first discovered skill. [Skills](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/skills.md) | Use the native skill mechanism; verify configured paths and reload behavior. No custom subagent or plan-mode emulation is needed for portable procedures. |
| Antigravity CLI | Global skills use `~/.gemini/antigravity-cli/skills`; project skills use `.agents/skills`. CLI settings use `~/.gemini/antigravity-cli/settings.json`. [Skills](https://antigravity.google/docs/skills), [Settings](https://antigravity.google/docs/settings?tab=cli) | Map only documented settings and verify skill discovery, managed values, and ownership on the installed CLI. |
| Antigravity IDE | Global skills use `~/.gemini/config/skills`, with a legacy `~/.gemini/antigravity/skills` location; project skills use `.agents/skills`. Skills are visible through Customizations. The settings page describes a UI and data directory but does not establish a supported directly writable settings-file schema. [Skills](https://antigravity.google/docs/skills), [Settings](https://antigravity.google/docs/settings?tab=cli) | Verify IDE skill discovery and supported settings controls. Do not infer the IDE's settings schema from the CLI. Keep IDE support in release scope while documenting native controls that cannot be automated. |

Antigravity documents global rules in `~/.gemini/AGENTS.md` or
`~/.gemini/GEMINI.md`, plus modular rules under `~/.gemini/config/rules`.
The CLI also has its own rules directory. Plain instruction files and modular
rule files have different formatting requirements; modular rules need trigger
frontmatter. [Rules](https://antigravity.google/docs/rules)

Synthesis: shared skill discovery and overlapping Gemini/Antigravity rule paths
make independent per-tool installation an unsafe assumption. Inventory and
deduplicate owned destinations, detect incompatible selections, and explain when
one native path affects multiple tools. The exact selection policy still needs
design. Do not claim isolated targeting solely from separate adapter names.

The native coverage above is sufficient to propose portable Markdown workflows.
It does not verify every setting, MCP integration, symlink behavior, installed
application version, or authentication-dependent runtime path.

## Candidate ECC components

Q16 confirms the four workflow purposes below. These sources remain candidate
inputs, not approved revision-pinned imports. ECC's checked repository
is [affaan-m/ECC](https://github.com/affaan-m/ECC); its old
`affaan-m/everything-claude-code` URL redirects there. Its
[MIT license](https://raw.githubusercontent.com/affaan-m/ECC/main/LICENSE)
must accompany relevant imports, together with source and adaptation records.

| Proposed optional workflow | Inspected source | Keep / adapt |
|---|---|---|
| Plan | [agents/planner.md](https://raw.githubusercontent.com/affaan-m/ECC/main/agents/planner.md) | Keep requirements, success criteria, code inspection, dependencies, implementation order, and testing considerations. Remove fixed model/tool metadata and automatic role mandates; add the toolkit's requirements interview and durable plan conventions. |
| Implement and verify | [skills/verification-loop/SKILL.md](https://raw.githubusercontent.com/affaan-m/ECC/main/skills/verification-loop/SKILL.md) | Use its verification/reporting process within a toolkit-authored scoped implementation procedure. Select checks from the target repository; do not inherit fixed npm commands or a universal coverage threshold. Report actual results and review the diff. |
| Review | [agents/code-reviewer.md](https://raw.githubusercontent.com/affaan-m/ECC/main/agents/code-reviewer.md) | Keep diff/context inspection and prioritized, actionable findings. Remove specific model/tool choices and blanket mandatory activation; respect repository conventions. |
| Handoff | Toolkit-authored; no ECC import selected | Save the goal, decisions, progress, changed paths, verification results, unresolved issues, and next action in repository Markdown. Include a plain-text resume instruction usable by another tool. |

The first and third sources are agent definitions, not ready-made portable
skills. Adapting their useful procedures is deliberate maintenance work under
Q8. Optional invocation must remain consistent with Q3 and native behavior with
Q7. No selected source authorizes overriding a consuming repository's rules.

Proposed distribution: one canonical skill directory per workflow, with small
native discovery mappings where needed. Prefer native support over wrappers;
namespacing and collision policy remain implementation details. Do not install
the complete ECC plugin or copy the separately installed interview skill merely
because it was used in this planning session.

## Upstream drift and update design implications

Source checks found redirects beyond ECC: Pi's repository now resolves to
[earendil-works/pi](https://github.com/earendil-works/pi), and the opened Codex
instruction/skill pages resolve to the `learn.chatgpt.com` documentation linked
above. Antigravity's older CLI settings and rules/workflows pages resolve to
the current settings and rules pages. Existing URL inventories need review.

Proposed implementation details, derived from these observations and Q9:

- Record requested and canonical source URLs, selected paths, revision/hash,
  license, last successful refresh, and local adaptations.
- Preserve the last valid snapshot if discovery or fetching fails; report a
  moved/missing source rather than deleting maintained content.
- Refresh reference mirrors separately from authored guides and installed
  behaviors. A reference change can flag an authored guide for review.
- Stage behavioral changes outside active linked sources. Compare the previously
  imported base, local adaptation, and new upstream; surface conflicts for review.
- Validate staged components before activation, retain the prior active version,
  and exercise recovery without overwriting personal configuration.

These are design proposals, not additional approved user requirements. The
update scheduler, review location, exact manifest format, activation mechanism,
and recovery commands have not been selected or implemented.

## Evidence still required during implementation

1. Capture installed versions and complete native settings/MCP mapping for all
   selected targets; resolve supported Antigravity IDE settings controls.
2. Test skill and instruction discovery in all six interfaces, including shared
   paths, existing collisions, custom configuration roots, and disabled features.
3. Demonstrate a second CLI/session resuming the saved project task without chat
   history or the original interview plugin.
4. Exercise an upstream update containing both a compatible change and a local
   adaptation conflict, with reviewed activation and recovery.
5. Complete the three accepted walkthroughs and the coordinated rename checks in
   the main plan. No application/configuration writes were made for this research.
