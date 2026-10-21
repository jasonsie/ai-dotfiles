---
name: iterative-retrieval
description: Find the files behind a question or task by searching in cycles, scoring what you find, and refining the search. Use when the user asks "where is this handled", "which files do I need to change", "find the code for X", or when a task needs codebase context you cannot name up front.
---

Find the files that matter for a question or task. You cannot know the right
search terms at the start, so search in short cycles and learn the codebase's
own words as you go. Use your CLI's own search and read tools.

## The loop

Dispatch, evaluate, refine, loop. Run at most 3 cycles, then proceed.

### 1. Dispatch

Run a broad first search.

1. Pick the likely folders and file types for the task.
2. Pick a few keywords from the task. Add synonyms.
3. Search for the keywords and list matching files with your search tool.
4. Skip tests, build output, and vendored code unless the task is about them.

### 2. Evaluate

Read the top candidates, at least their headers, exports, and the matching
lines. For each file, write down three things:

- **Relevance**, from 0 to 1.
- **Reason**, in one line.
- **Missing context**: what you still need to know after reading it.

Relevance bands:

- **0.8-1.0 high**: directly implements the target behavior.
- **0.5-0.7 medium**: related patterns or types.
- **0.2-0.4 low**: only loosely related.
- **0-0.2 none**: not relevant. Drop it.

### 3. Refine

1. Add the words the codebase actually uses, taken from the high-scoring files.
2. Add new folders or file patterns those files point to.
3. Drop paths you scored below 0.2.
4. Aim the next search at the gaps you listed.

### 4. Loop

Repeat from step 1 with the refined search. Stop when either is true:

- You have at least 3 files scoring 0.7 or more, and no critical gaps.
- You have run 3 cycles. Use the best files you have and say what is still missing.

Three strong files beat ten weak ones.

## Examples

### Bug fix

```
Task: "Fix the authentication token expiry bug"

Cycle 1:
  DISPATCH: Search for "token", "auth", "expiry" in src/**
  EVALUATE: Found auth.ts (0.9), tokens.ts (0.8), user.ts (0.3)
  REFINE: Add "refresh", "jwt" keywords; exclude user.ts

Cycle 2:
  DISPATCH: Search refined terms
  EVALUATE: Found session-manager.ts (0.95), jwt-utils.ts (0.85)
  REFINE: Sufficient context (2 new high-relevance files, 4 in total)

Result: auth.ts, tokens.ts, session-manager.ts, jwt-utils.ts
```

### New feature

```
Task: "Add rate limiting to API endpoints"

Cycle 1:
  DISPATCH: Search "rate", "limit", "api" in routes/**
  EVALUATE: No matches - codebase uses "throttle" terminology
  REFINE: Add "throttle", "middleware" keywords

Cycle 2:
  DISPATCH: Search refined terms
  EVALUATE: Found throttle.ts (0.9), middleware/index.ts (0.7)
  REFINE: Need router patterns

Cycle 3:
  DISPATCH: Search "router", "express" patterns
  EVALUATE: Found router-setup.ts (0.8)
  REFINE: Sufficient context

Result: throttle.ts, middleware/index.ts, router-setup.ts
```

## Handing work to a sub-agent

Only if your CLI can start a sub-agent. Pass it the files you found, each with
the reason it matters (for example: "`throttle.ts` - existing limiter to
reuse"). Include any gaps you could not close. Do not pass the whole search
history. If your CLI has no sub-agent, keep the list and reasons in your own
notes and carry on.

## Tips

- Start broad. The first cycle usually shows the project's naming.
- Write the gaps down; they drive the next search.
- Exclude confidently. A file under 0.2 will not become relevant.

Adapted from `iterative-retrieval` in affaan-m/everything-claude-code (MIT License;
see LICENSE here).
