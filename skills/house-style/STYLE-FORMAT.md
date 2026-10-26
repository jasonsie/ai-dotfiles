# STYLE.md format

What every document shares. The global `STYLE.md` is the full file; a project's `docs/house-style/STYLE.md` is a **delta**: the same headers, only what differs, each line overriding its global counterpart.

## Structure

```md
# House style

{One line: the company, and who its documents are for.}

## Voice and tone

- {Register, person (we / you), sentence length, hedging.}

## Formatting

- {Conventions common to every document: heading style, bullets vs prose, tables.}

## Terminology

- **{Preferred term}**: {what it names: customers, teams, releases, the product}. _Avoid_: {terms it replaces}

### Never in customer-facing docs

- **{Internal codename}**: {what it names}

## Branding

- {Colors, fonts.}

## Audience defaults

- **{Audience, e.g. execs}**: {what changes for them: depth, what comes first}
```

## Rules

- Rules, not a brand bible: it is read before every document, so a screen at most.
- Every section filled or "none seen".
- One entry per audience: an exec memo and a team update follow different rules.
- Codenames under "Never in customer-facing docs": that keeps them out of release notes and updates.
- Length, section order and markers belong to the type's template, not here.
