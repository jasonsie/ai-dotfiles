---
name: house-style
description: The company's house style (voice, formatting, terminology, templates, branding) for documents written for people. Use when the user says "match our format", "use our style", "write like this", "set up our house style", or pastes a sample doc or brand guide to learn from.
---

The company's style for documents people read: two layers, one layout. This folder, linked into every CLI from the ai-dotfiles repo, is the global layer: `STYLE.md` for what every document shares, `templates/<type>.md` per document type. A project adds **deltas** at `docs/house-style/` (or the path a `House style: <path>` line in its `AGENTS.md` names): the same file names, holding only what differs. Artifacts agents read (a `to-spec` spec, tickets, a PR body, a handoff) follow their own skills.

## Types

| Type | When |
|---|---|
| `spec` | what to build and why, for the people who decide or review it |
| `update` | progress for stakeholders: shipped, next, blocked |
| `plan` | steps to a goal, with owners and dates |
| `memo` | one decision or proposal, argued for its reader |
| `release-notes` | what changed for customers, per release |

A type has a template once `templates/<type>.md` exists; capture adds types.

## Apply

Pick the type whose *When* fits the request, naming it when the request didn't; none fits → skip the `<type>.md` files. Load each file that exists, later ones overriding earlier:

1. `STYLE.md`
2. `templates/<type>.md`; none → the writing skill's own structure
3. the project's `STYLE.md`, then its `<type>.md`

## Capture

1. **Sample.** One real, recent, ordinary document the company published, and its audience. People describe the style they intend, not the one they write, so ask for the document itself. A showpiece teaches the exception; a style guide adds what they believe the rules are.
2. **Layer.** The sample's type has no template → it seeds `templates/<type>.md`, and `STYLE.md` when that is missing too; it has one → the sample writes the project's delta. The user may name the layer.
3. **Extract**, the sample as evidence, into the sections of [`STYLE-FORMAT.md`](STYLE-FORMAT.md) and [`TEMPLATE-FORMAT.md`](TEMPLATE-FORMAT.md); ask only what the sample cannot show. A rule seen once is an *assumption* until a second sighting or the user's word; list the assumptions.
4. **Write**, on a new branch in that repo: the global layer at this folder's real path in ai-dotfiles, with a new type's row in the table above; the project layer at its delta path. Done when every section is filled or says "none seen". Global files are live in every CLI the moment they are written; the merge keeps them.

Reply:

```
HOUSE STYLE CAPTURED: <type>, <global | project>
- Sections: <in order>
- Key terms: <the 2-3 that matter most>
- Assumptions: <anything guessed>
<files>, branch <name>: live now; merge to keep.
```
