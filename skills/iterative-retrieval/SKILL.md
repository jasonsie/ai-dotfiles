---
name: iterative-retrieval
description: Find the files behind a question or task by searching in cycles, scoring what you find, and refining the search. Use when the user asks "where is this handled", "which files do I need to change", "find the code for X", or when a task needs codebase context you cannot name up front.
---

Find the files that matter for a question or task. You cannot know the right
search terms up front, so search in short cycles and learn the codebase's own
words. Use your CLI's search and read tools.

## The loop

Dispatch, evaluate, refine, repeat. At most 3 cycles, then proceed.

### 1. Dispatch

Run a broad search.

1. Pick likely folders and file types.
2. Pick keywords from the task, plus synonyms.
3. Search them and list matching files.
4. Skip tests, build output, and vendored code unless the task is about them.

### 2. Evaluate

Read the top candidates: headers, exports, matching lines. For each file write:

- **Relevance**, 0 to 1.
- **Reason**, one line.
- **Missing context**: what you still need after reading it.

Bands:

- **0.8-1.0 high**: directly implements the target behavior.
- **0.5-0.7 medium**: related patterns or types.
- **0.2-0.4 low**: loosely related.
- **below 0.2 none**: drop it.

### 3. Refine

1. Add the words the codebase uses, taken from high-scoring files.
2. Add folders or file patterns those files point to.
3. Drop paths scored below 0.2.
4. Aim the next search at the listed gaps.

### 4. Loop

Repeat from step 1. Stop when either holds:

- At least 3 files score 0.7 or more, and no critical gaps.
- 3 cycles are done. Use the best files and say what is still missing.

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

Only if your CLI can start one. Pass the files found, each with why it matters
(for example "`throttle.ts` - existing limiter to reuse"), plus any unclosed
gaps. Not the whole search history. Without sub-agents, keep the list in your
own notes.

Adapted from `iterative-retrieval` in affaan-m/everything-claude-code (MIT License;
see LICENSE here).
