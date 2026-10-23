---
name: house-style
description: The company's house style (voice, formatting, terminology, templates, branding) for documents written for people. Use when the user says "match our format", "use our style", "write like this", "set up our house style", or pastes a sample doc or brand guide to learn from.
---

The style lives in [`STYLE.md`](STYLE.md), beside this file. This folder links into every CLI from the ai-dotfiles repo, so one capture applies in every project and every CLI.

## Apply

When writing a document for people, follow `STYLE.md`; its templates replace a skill's default structure. While it says "None captured yet", use the default format.

## Capture

1. **Get a sample.** One real, recent, ordinary document the company published (a shipped PRD, a launch update, a board memo) and the audience it was written for. When the user only describes the style, ask for the document: people describe the style they intend, not the one they write. A showpiece teaches the exception. A style guide or template adds what they believe the rules are, even when stale.
2. **Extract** from the sample as evidence; ask only about what it cannot show. Cover:
   - Voice and tone.
   - Formatting: headings, bullets vs prose, length, TL;DR, status markers, tables.
   - Terminology: what they call customers, teams, releases and the product; preferred and banned terms; internal codenames.
   - Templates: the required sections per document type.
   - Branding: colors, fonts.
   - Audience defaults: one entry per audience, since an exec memo and a team update follow different rules.
3. **Confirm.** Show the draft. A rule seen once is an *assumption* until a second sighting or the user's word makes it a convention; list assumptions for the user to settle.
4. **Write** `STYLE.md` at this folder's real path in the ai-dotfiles repo, on a new branch there, replacing the whole file with one section per cover item above. Rules only, a screen or two, with codenames under "never in customer-facing docs". Every section is filled or says "none seen". Done when the file is written; it goes live once merged.

Reply with:

```
HOUSE STYLE CAPTURED
- Voice: <one line>
- Formatting: <one line>
- Key terms: <the 2-3 that matter most>
- Templates: <document types with a house format>
- Assumptions: <anything guessed>
Written to skills/house-style/STYLE.md in ai-dotfiles, branch <name>: review, commit and merge to apply it everywhere.
```
