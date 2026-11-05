# Domain Docs

How the engineering skills read this repo's domain documentation.

## Before exploring, read these

- **`docs/how-it-works.md`**: its Glossary section is this repo's glossary, and its Principles
  section holds the standing decisions. There is no `GLOSSARY.md`.
- **`docs/plans/<topic>.md`**, when one exists: a design in progress, its decisions and their
  reasons. Folded into `docs/how-it-works.md` and deleted once built.
- Older decision records are in git history (`git show 3507344:docs/adr/`). There is no `docs/adr/`.

If one of these does not exist, proceed silently.

## Where new terms and decisions go

A new term goes into the Glossary of `docs/how-it-works.md` (during a design, the plan's Terms
section first). A new decision goes into the plan, then into `docs/how-it-works.md` when built.
Do not create `GLOSSARY.md` or `docs/adr/`.

## Use the glossary's vocabulary

Name a domain concept by its glossary term, in issue titles, proposals and test names alike. A
concept the glossary lacks is either language the project does not use or a real gap; note a gap.

## Flag conflicts

When your output contradicts a principle in `docs/how-it-works.md` or a decision in a plan, say so
explicitly rather than overriding it silently.
