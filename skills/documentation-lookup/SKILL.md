---
name: documentation-lookup
description: Fetch current library and framework docs through the Context7 tools instead of relying on memory, matching the version the repo uses. Use for setup questions, API references, code examples that depend on a library, or when the user names a framework such as React, Next.js, or Prisma.
---

When a request depends on a library, framework, or API, fetch its current
documentation with the Context7 tools (`resolve-library-id` and `query-docs`)
instead of relying on training data.

## When to use

- Setup or configuration questions ("How do I configure Next.js middleware?").
- Code that depends on a library ("Write a Prisma query for...").
- API or reference questions ("What are the Supabase auth methods?").
- Any named framework or library.

## Steps

### 0. Find the version the repo uses

Before resolving, read the library's version from the repo's manifests:
`package.json`, `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml`,
or a lockfile. If the codemap facts output has already been run, its
`## Manifests` section lists them. If the library is not in the repo, or the
user names a version, use that instead.

### 1. Resolve the library ID

Call `resolve-library-id` with:

- **libraryName**: the library name from the question (for example `Next.js`).
- **query**: the user's full question. It improves ranking.

You need an ID like `/org/project` or `/org/project/version` before you query
docs.

### 2. Pick the best match

- **Name**: the closest match to what was asked for.
- **Benchmark score**: higher is better, 100 is the top.
- **Source reputation**: prefer High or Medium.
- **Version**: prefer the version ID that matches the repo's version from step 0
  (for example `/org/project/v1.2.0`). If none matches, take the nearest and say so.
- Prefer official packages over community forks.

### 3. Fetch the docs

Call `query-docs` with the chosen `libraryId` and the user's specific question.

Make at most 3 calls in total (`resolve-library-id` and `query-docs` together)
per question. If the answer is still unclear after 3, say what is uncertain and
use the best information you have. Do not guess.

### 4. Use the docs

- Answer from the fetched, current information.
- Include short code examples from the docs when they help.
- Say which version you used, and where it came from ("Next.js 15, from
  `package.json`"). If it was not the repo's version, say that.

## Example: Next.js middleware

1. `package.json` lists `"next": "15.1.0"`.
2. Call `resolve-library-id` with `libraryName: "Next.js"` and
   `query: "How do I set up Next.js middleware?"`.
3. Pick `/vercel/next.js/v15.1.0` if listed, otherwise `/vercel/next.js`.
4. Call `query-docs` with that `libraryId` and the same question.
5. Answer with a minimal `middleware.ts` from the docs. State that you used 15.1.0.

## Best practices

- **Be specific**: use the user's full question as the query.
- **Match the version**: the repo's version beats the newest one.
- **No secrets**: remove API keys, passwords, tokens, and other secrets from any
  query sent to Context7. Check the user's question for them before you pass it
  to either tool.

Adapted from `documentation-lookup` in affaan-m/everything-claude-code (MIT License;
see LICENSE here).
