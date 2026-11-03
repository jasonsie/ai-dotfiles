---
name: small-commits
description: "Make the commits a reviewer can read, the way this setup's hook accepts them: under 300 changed lines, one concern, a `type(scope): outcome` subject and the Why:, Scope: and Verified: trailers. Use when the user says the changes are ready to commit, when a small-commits message blocked a `git commit`, or when a change has to be split into commits."
---

# Small commits

A reviewer, human or agent, reads one commit at a time. Each commit is one concern, under
300 changed lines, green on its own, and says why. The hook in
[scripts/small_commits.py](scripts/small_commits.py) measures every `git commit` a session
runs and blocks what breaks this; `ai-dotfiles commit check [git commit args]` says
beforehand what it would say.

## When the changes are ready

1. **Measure.** `ai-dotfiles commit check -a` (or with the paths you mean to stage): the
   lines by file, lockfiles and generated files already left out.
2. **Plan.** One line per commit: `type(scope): outcome`, its files, its line count, its
   trailers. Over 300 lines, or two concerns in one diff: split (below). Show the plan and
   wait for the user's go.
3. **Commit** in the plan's order, staging each commit's own hunks (`git add -p` for a file
   two commits share). Every message carries the trailers; split commits add `Part: n/m`.
4. **Report** the `git log --oneline` of what landed.

## Splitting

A sub-commit is one concern that leaves the tree working:

- prerequisites first: the refactor, then the behavior change, then the docs;
- a test lands with the code it covers;
- a refactor and a behavior change go in separate commits;
- tests and build pass at every commit, so each is bisectable and reviewable alone.

Cutting by file or by size alone satisfies the hook and fails the reviewer.

## The message

```text
type(scope): what the change achieves, imperative, 72 characters at most

Body, when the subject cannot carry the why alone.

Why: the reason for the change, one line
Scope: the one concern it touches, e.g. daily-log writer
Verified: what ran, e.g. unittest 41 passed; or none
Part: 2/4
```

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert. The trailers
are the message's last paragraph; `git commit --trailer "Why: ..."` adds them too.

## When blocked

- **over 300**: split; or rerun the same command once to commit as is (the hook lets the
  identical retry through and says so).
- **over 600, the wall**: split. A diff that cannot be split (one vendored or generated
  file not yet marked in `.gitattributes`) goes to the user; with their go, rerun with
  `ALLOW_LARGE_COMMIT="<reason>" git commit ...` and a `Large-commit: <reason>` trailer. The
  user grants this; ask them.
- **the message needs work**: the reason names the subject rule or the missing trailers.
- **"small-commits failed ... not checked"**: the commit ran unchecked; say so in your reply.

## What the hook counts

Added plus deleted lines of what the commit would hold: the staged diff; with `-a`, every
tracked change; with paths, those paths; with `--amend`, the result against the parent. Left
out: binaries, lockfiles, and files `.gitattributes` marks `linguist-generated` or `-diff`
(mark a repo's generated output there, e.g. `docs/upstream/** linguist-generated`). A commit
that finishes a merge, cherry-pick, revert or rebase is git's and passes untouched.
