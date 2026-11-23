# Skill mechanics

The skill-specific branch of [`writing-for-agents`](SKILL.md): what changes when the document is a skill (the invocation choice, router skills, frontmatter and packaging limits, instruction patterns, scripts, and testing). Everything else about writing it is the universal reference in `SKILL.md`.

## Invocation

Two choices, trading the two loads:

- A **model-invoked** skill keeps a `description`, so the agent can fire it autonomously, and other skills can reach it. You can still type its name: model-invocation always _includes_ user reach; a description only ever adds agent discovery, never removes the human's. The description is the skill's top-level context pointer, forced to stay loaded at all times: permanent context load in exchange for discoverability. A model-invoked skill whose content is all reference is also one home for shared reference: another skill can invoke it, so reference needed by several skills lives in one place. Mechanics: omit `disable-model-invocation`, and write a model-facing description carrying the trigger branches (the pointer-writing rules in `SKILL.md` apply in full).
- A **user-invoked** skill strips the description from the agent's reach: only the human typing its name can invoke it, and no other skill can. Zero context load, but it spends cognitive load: you are the index that must remember it exists. Mechanics: set `disable-model-invocation: true`; the `description` becomes human-facing: a one-line summary, trigger lists stripped.

Pick model-invocation only when the agent must reach the skill on its own, or another skill must. If it only ever fires by hand, make it user-invoked and pay no context load.

Shared reference that two user-invoked skills both need can live in neither: with no descriptions, neither can fire the other. Push it to a plain file outside the skill system: external reference any skill can point at.

## Splitting by invocation

The invocation cut of splitting (the sequence cut lives in `SKILL.md`): split off a model-invoked skill when you have a distinct leading word that should trigger it on its own (a trigger word you actually use in your prompts), or another skill must reach it. You pay context load for the new always-loaded description, so that independent reach has to be worth it.

## Router skills

When user-invoked skills multiply past what you can remember, that piled-up cognitive load is cured by a **router skill**: one user-invoked skill that names the others and when to reach for each, so the human has one skill to remember instead of many. It can only hint, never fire them: user-invoked skills have no description, so nothing but the human can reach them.

## Frontmatter limits

- **`name`:** at most 64 characters of lowercase letters, digits and hyphens, with neither `anthropic` nor `claude` in it. It names the activity (`processing-pdfs`, `pdf-processing`), in one pattern across the collection.
- **`description`:** at most 1,024 characters of plain text. A placeholder is an example value or a capitalised word (`approve 57`, `archive/NAME`): angle brackets read as XML tags, and Claude Code lists them escaped. A model-facing description says what the skill does, then when to use it, in the third person ("Extracts text from PDFs", where "I can…" and "You can…" shift the point of view of the system prompt it is injected into and hurt discovery).

## Packaging and hygiene

- **Size cap:** keep each `SKILL.md` body under 500 lines and the file under 20,000 bytes. Push heavy reference into sibling Markdown files behind a context pointer.
- **One level deep:** `SKILL.md` itself points at every reference file. A file reached only through another reference file gets a partial read (`head -100`) or none.
- **Contents first:** a reference file over 100 lines opens with a `## Contents` list, so a partial read still shows its whole scope.
- **Names and paths:** a file name says what is inside (`form-validation-rules.md`, where `doc2.md` says nothing); paths use forward slashes.
- **Folder hygiene:** keep scratch and test files (`test-*.md`, `CREATION-LOG.md`) out of `skills/`, and verify every relative Markdown link resolves.

## Instruction patterns

- **Degrees of freedom:** specify a step as tightly as it is fragile. A fragile or ordered operation gets the exact command and the words "run exactly this"; a preferred pattern gets a template with parameters; work that turns on context gets heuristics in prose.
- **One default:** name one tool or approach, then the case that needs another ("pdfplumber; for scanned pages, OCR"). A menu of equals makes each run choose differently.
- **One term per concept**, the same word from the description to the last line.
- **Feedback loop:** on quality-critical work, write the loop as steps: run the validator, fix what it reports, run it again, go on only when it passes. Before a batch or destructive change, the agent writes the plan to a file and a script validates that file first.
- **Shape by example:** where output quality turns on style, give input/output pairs; where the format is fixed, give the template and say it is exact.
- **Dated facts:** the main text states the current way; what stopped holding sits under an "Old patterns" heading with its date.

## Scripts

- **Script the deterministic:** an operation with one right result is a script in the skill's `scripts/`. Only its output costs context, and every run does the same thing.
- **Run or read:** say which a script is for: "Run `scripts/analyze.py`" or "See `scripts/analyze.py` for the algorithm".
- **Solve, don't defer:** the script handles its own failures and prints what was wrong and what is valid ("Field `signature_date` not found. Available: …"), so the agent fixes the input in one step.
- **Reasoned constants:** each timeout, retry count or threshold carries its reason in a comment.
- **Named dependencies:** state the command or package a step needs where the skill first uses it.
- **MCP tools** are written fully qualified: `Server:tool_name`.

## Testing a skill

Start from failures, before writing much: run the task without the skill and note where the agent goes wrong. Turn those gaps into three scenarios (the prompt, its files, the expected behaviour) and keep them as the measure: write only what closes a gap, re-run, compare with the baseline. Run them on each model tier that will load the skill: a small model shows missing guidance, a large one over-explaining.

Then watch real use. A bundled file never read is unneeded or badly pointed at; one read on every run belongs in `SKILL.md`; a skill that does not fire needs a sharper description.

### Pressure test (optional)

For discipline-enforcing or behavior-shaping skills, run a lightweight RED→GREEN pressure test before shipping: give a fresh subagent (where the CLI has none, a fresh session) a realistic, tempting scenario **without** the skill to observe the baseline failure and exact rationalizations (RED), write minimal guidance matched to that failure mode (see `Match the form to the failure` in `SKILL.md`), then re-run **with** the skill (GREEN) and close any remaining loopholes. Skip for pure reference skills.
