---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Where possible, load the `tdd` skill (the Skill tool, where the CLI has one) at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, load the `spec-review` skill (the Skill tool, where the CLI has one) to review the work. Before fixing any finding, verify it against the codebase and spec: fix confirmed issues and re-run the covering tests; push back with technical reasoning (citing code, tests, or spec) on findings that are wrong, break existing behavior, or violate YAGNI, and ask the user when a finding is ambiguous or conflicts with the spec.

Commit your work to the current branch.

Adapted from `implement` in mattpocock/skills (MIT License; see LICENSE here); review-verification guidance adapted from `receiving-code-review` in obra/superpowers (MIT License; see `THIRD-PARTY-NOTICES.md`).
