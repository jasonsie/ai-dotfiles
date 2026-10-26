# Template format

One file per document type, `templates/<type>.md`, where `<type>` is the id in the `SKILL.md` type table. It loads on every write of that type: about twenty lines. A project's `docs/house-style/<type>.md` is a **delta** on it.

## Structure

```md
# {Type}

## Sections

1. **{Section}**: {one line: what goes there}
2. **{Section}** (optional): {one line}

## Length

{Target: words, pages or reading time.}

## Audience

{Who reads it; what comes first for them.}

## Markers

{Status markers, TL;DR, tables, dates, owners this type uses.}
```

## Delta

The same headers, only those that change. Under `Sections`, marked edits; the other headers carry the replacing text.

```md
## Sections

+ **Rollout**, after Risks: {one line}
− **Branding**
Summary → **TL;DR**

## Length

One page.
```

`+` adds a section at the place named, `−` removes one, `→` renames one.

## Rules

- The *When* label lives in the `SKILL.md` type table, not here.
- Sections in the order they appear, one line each.
- A delta is a few lines; a project whose document shares little with the template gets a new type instead.
