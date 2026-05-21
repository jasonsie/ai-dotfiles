---
name: deep-review
description: Run multi-dimensional code review (correctness + security + architecture) before committing
---

# Deep Review

Run a three-dimensional review of staged changes before commit:

1. **Correctness** — Logic errors, edge cases, off-by-one, null-handling.
2. **Security** — Injection, auth bypass, secrets exposure, OWASP Top 10.
3. **Architecture** — Coupling, layering violations, abstraction leaks, test coverage.

For each dimension, spawn a dedicated reviewer sub-agent in parallel. Aggregate findings into a single report:
- CRITICAL: must fix before commit
- HIGH: strongly recommended
- MEDIUM: fix if time permits
- LOW: optional / style

If any CRITICAL or HIGH findings exist, do NOT proceed with the commit; report them and wait for the user's decision.
