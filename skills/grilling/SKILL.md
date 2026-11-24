---
name: grilling
description: Interview the user relentlessly about a plan, decision, or design until both share an understanding, one question at a time, each with a recommended answer. Use when the user wants to stress-test their thinking or says "grill me", "grilling", or a similar trigger.
---

Interview the user relentlessly until you reach a shared understanding. Map the
topic as a **design tree**: every decision branches into the decisions that
depend on it. Settle it one decision at a time, starting with decisions whose
prerequisites are already settled.

## Each question

Ask **one question per message**, in plain text:

- Open with one or two sentences in everyday words: what is being decided and
  why it matters now. Show the evidence you found (counts, file paths, quotes)
  when it helps the user choose.
- Offer numbered options. Put your recommendation first, mark it
  "(recommended)", and give every option its tradeoff in one line.
- Word the question so "y" or "yes" accepts your recommendation. The user may
  combine options ("1 + 3") or answer in their own words, so do not use a
  single-choice question tool.
- If the user does not understand a question, explain it again more simply,
  with a concrete example, and ask again.

## Facts and decisions

Finding facts is your job, never the user's. When a question depends on
something you can look up (files, configuration, tool output, documentation),
look it up first, using a subagent with a fresh context window if your CLI has
one, and ask only about what remains a decision. When an answer or new evidence
changes the tree, rework the remaining questions instead of asking the old ones.

After each answer, record the decision and its reason where the task's state
lives, so another session or CLI can resume the interview.

## Finish

The interview ends when every branch is settled and nothing is silently
assumed. Summarize the decisions and wait for the user to confirm before acting
on them.

Adapted from `grilling` in mattpocock/skills (MIT License; see LICENSE here).
