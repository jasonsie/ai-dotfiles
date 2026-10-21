---
name: architect
description: Assess a codebase's architecture and report its current structure, technical debt, and red flags, each tied to a file. Use when the user says "review the architecture", "assess this repo", "what is the tech debt", "is this design sound", or is about to make a large design or refactoring decision.
---

Assess the architecture of the current repository. Report what is there and what
is wrong with it. Do not change code. The only file you may write is an
Architecture Decision Record (ADR), and only as described at the end.

## Before you start

1. If `docs/CODEMAPS/` exists, read `INDEX.md` and the maps it points to first.
2. If it does not, suggest running the `codemap` skill to build the maps. If the
   user declines, go on from the key files: manifests, entry points, the
   top-level folders, and any README or design notes.
3. Read the key files the maps point to. Do not assess from the maps alone.

## Review process

### 1. Current state

- Describe the structure: the main parts, what each one does, how they connect.
- Name the patterns and conventions the code already follows.
- List technical debt: duplication, dead code, outdated dependencies, missing
  tests, workarounds.
- Note what limits growth: scale, performance, deployment, team size.

### 2. Requirements

Ask the user only what the code cannot tell you:

- What the change or goal is.
- Non-functional needs: performance, security, scalability, availability.
- Integration points and data flow the change must respect.

### 3. Design proposal

Only when the user wants a change designed, not just assessed:

- The parts and what each is responsible for.
- Data models and API contracts.
- How the parts connect.

### 4. Trade-offs

For each design decision, state:

- **Pros** and **cons**.
- **Alternatives** you considered.
- **Decision** and the reason for it.

## Principles to check against

- **Modularity**: one job per part, high cohesion, low coupling, clear interfaces.
- **Scalability**: stateless where possible, efficient queries, caching where it pays.
- **Maintainability**: consistent patterns, easy to test, easy to understand.
- **Security**: least privilege, input checked at the boundaries, safe by default.
- **Performance**: no needless work, no needless network calls.

## System design checklist

Use it when designing a new system or feature. Skip lines that do not apply.

- Functional: user stories, API contracts, data models, main flows.
- Non-functional: latency and throughput targets, scale, security needs, uptime.
- Technical: component responsibilities, data flow, integration points, error
  handling, test strategy.
- Operations: deployment, monitoring and alerts, backup and recovery, rollback.

## Red flags

Look for these. Report each one you find.

- **Big Ball of Mud**: no clear structure.
- **Golden Hammer**: the same solution used for everything.
- **Premature optimization**: speed work before it is needed.
- **Not Invented Here**: rejecting existing solutions.
- **Analysis paralysis**: too much planning, too little building.
- **Magic**: behavior that is unclear or undocumented.
- **Tight coupling**: parts that depend on each other too much.
- **God object**: one class or module that does everything.

## Report

Give the report in chat: current structure, technical debt, red flags, in that
order. Do not save it to a file, including `docs/CODEMAPS/`; findings go stale
faster than maps. Every finding names the file it came from (`path/to/file:line` when you
can). Drop any finding you cannot tie to a file. Keep it short; lead with the
risks that matter most.

## ADRs

Write an ADR only when the user makes a decision.

1. Find the repo's ADR folder: `docs/adr/`, `adr/`, or `docs/decisions/`.
2. Match the format and numbering of the ADRs already there.
3. If the repo has no ADR folder, ask the user where to put it before writing.
4. Record the context, the decision, the alternatives, and the consequences.

Adapted from the `architect` agent in affaan-m/everything-claude-code (MIT License;
see LICENSE here).
