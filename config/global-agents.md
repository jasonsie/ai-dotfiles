## Replies

Report to me telegraphically: fragments over sentences, brevity over grammar.

## Code

Make code self-explanatory through clear names and structure. Add inline comments only
for non-obvious why (invariants, constraints, workarounds, tradeoffs), not what or how.
Leave docstrings and public API docs to repo conventions; keep existing comments unless
your edit makes them stale.

## Documents

Before writing a document for people (such as a spec, update, plan, memo or release
notes), load the `house-style` skill and follow it.

## Subagents

If available, delegate self-contained subtasks to subagents on a cheaper, faster
model; run independent ones in parallel. Keep the strongest model for planning,
review, and hard debugging; verify subagent results.
