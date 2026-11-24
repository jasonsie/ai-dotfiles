# Phase boundaries

A **phase** is a chunk of work inside a session: the grilling, the implementation, the
review. The definition is fuzzy on purpose: a phase ends when you think *"ok, we're done
with that"*.

The **phase boundary** is the gap between two phases, and it is the only place this
decision belongs. Mid-phase there is no decision to make: continue, or split the work
that's left into sub-agents. Compacting mid-phase makes the agent lose the thread.

## The five options

| Option | What it does |
| --- | --- |
| **Continue** | Stay in the session. No context switch at all. |
| **Clear** | Empty the context window and start from nothing. |
| **Handoff** | The `handoff` skill writes a portable Markdown file; seed a session anywhere with it. |
| **Sub-agent** | Send the task to its own context window and get a report back. |
| **Compact** | Compress this context and carry on from the summary. |

Each CLI's way to do them (from its docs):

| | Claude Code | Codex CLI | Pi | Antigravity |
| --- | --- | --- | --- | --- |
| Clear | `/clear` | `/clear` or `/new` | `/new` | `/clear` (or `/new`) |
| Compact | `/compact [focus]` | `/compact` | `/compact [focus]` | `/compact` (release notes only) |
| Resume a cleared session | `/resume` | `/resume` | `/resume` | `/resume` |
| Sub-agent | ask for one | ask for one | none documented | ask for one |
| Run a skill | `/<name>` | `$<name>` | `/skill:<name>` | `/<name>` |

## The tree

Work top to bottom at the boundary. The first **yes** wins.

**1. Can you continue in this session?** Two things make the answer yes: the next phase
needs this phase as a **primary source**, or there is enough of the window left (the part
where the model still reasons sharply) for the
next phase to fit. Grilling, then implementation, is the standard yes: the implementation
wants the reasoning verbatim, not a summary of it. Continue costs nothing and loses
nothing, so rule it out before anything else.

**2. Is the context irrelevant to what comes next?** Is everything in this session (the
exploration, the decisions, the dead ends) disposable? If so, **clear**. It is the
cheapest move: it takes no time and hands back the whole window, and the old session
stays resumable.

The cost of getting this wrong is one-way. Clear a *relevant* context and you lose the
**why** behind what you built, and no amount of reading the diff back returns it.

**3. Do you need to hand off?** `handoff` is narrow. You need it only when you are:

- moving to **another CLI** (Claude Code to Codex),
- moving to **another directory** or repository,
- sending the work to a **colleague**,
- or forking a side task you found **mid-phase** without derailing what you're doing.

That list is the whole clause. What `handoff` buys is **portability**: a file that
travels. If nothing is travelling, you don't need it.

**4. Can the task be done AFK?** Is it scoped tightly enough to run with you away from
the keyboard, no steering? Then send it to a **sub-agent** and leave this session
untouched. Automated review is the standard case: the agent reads the diff and reports,
and you aren't needed while it does. Pi documents no sub-agents; there, go on to 5.

**5. Otherwise, compact.** Relevant context, same CLI, same directory, and you need to
stay in the loop: this is where the tree lands, and it lands here often. Where the CLI
takes a focus (Claude Code, Pi), pass one (`/compact we're going to review this area`)
so the summary keeps what the next phase needs.

Compact is the **default, not the first reach**. It sits at the bottom because the four
questions above it are all cheaper or more precise. The failure mode when people start
here is a fresh session that is confidently wrong about a decision the summary flattened.

## Primary and secondary sources

Every move except **Continue** turns a **primary source** into a **secondary source**:
the session as it happened, replaced by a summary of it. The trade is always the same:

| Source | Information | Noise | Room to move |
| --- | --- | --- | --- |
| Primary (continue) | Full | Lots | Little |
| Secondary (compact, `handoff`) | Lossy | Less | Lots |

This is why question 1 comes first. You only pay the lossiness when staying costs more
than it saves.

## These are judgement calls

The questions are not objective: each has taste in it, and the same boundary can go two
ways on two days. The value is in asking them **in order**, at the boundary rather than
in the middle of the work.
