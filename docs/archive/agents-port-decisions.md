# Agents subsystem — grilling decisions (2026-07-22)

Session output of `/grill-me` on `tasks.md` §Agents. Decisions are **locked**
unless explicitly revisited. Evidence lines cite files inspected during the
session.

---

## Q1 — Collision policy: **(A) Skip and cherry-pick**

`tools/agents/` is a flat namespace consumed by three adapters, so a filename
collision is a hard overwrite, not a merge.

**Decision**: never overwrite a workspace agent with an ECC one. Colliding
names are skipped; worthwhile ECC *content* is harvested by hand into the
existing workspace file, keeping workspace frontmatter, scope boundaries,
model tier, and 繁中 idiom.

Collisions identified:

| Workspace | ECC | Resolution |
|---|---|---|
| `code-reviewer.md` (35L, 繁中) | `code-reviewer.md` (237L, EN) | cherry-pick |
| `security-reviewer.md` (21L, read-only) | `security-reviewer.md` (108L, has `Write`,`Edit`) | cherry-pick; **do not import write access** |
| `doc-writer.md` | `doc-updater.md` | semantic collision; skip ECC |
| `reviewer.md` (opus, 架構決策) | `architect.md` (211L, opus) | semantic collision; cherry-pick into `reviewer.md` |

**Rationale**: the workspace agents are a *partitioned team* (explicit negative
scope, e.g. `❌ 架構決策 → reviewer`) whose cost tiering (haiku/sonnet/opus)
only works because cheap agents refuse expensive work and hand off. ECC agents
are self-sufficient and overlapping — importing them wholesale defeats the
routing. Overwriting would also re-create the upstream-provenance problem that
`skills-lock.json`'s removal deliberately eliminated (tasks.md:357).

---

## Q2 — Admission rule: **(A) Fill-a-hole, language-matched**

An agent must fill a genuine gap in the current partition **and** target a
language actually in use.

**Measured footprint** (`find` across `~/Developer/repo`, node_modules excluded):
267 TS/TSX · 63 Python · 1 Rust · 1 Go · 0 Java/Kotlin/C++/Swift/PHP.
Manifests: 11 `package.json`, 2 `pyproject.toml`, 1 `pom.xml` (book sample code).
The workspace repo itself is 116 Markdown + 25 shell.

**Admit (5)**: `planner`, `tdd-guide`, `refactor-cleaner`,
`typescript-reviewer`, `python-reviewer`.

**Reject (18)**:
- *Wrong language (14)* — all `cpp-*`, `go-*`, `java-*`, `kotlin-*`, `rust-*`
  reviewer/build-resolver pairs.
- *Not software dev (1)* — `chief-of-staff` (email/Slack/LINE triage).
- *Redundant (2)* — `docs-lookup` (Context7 already a skill), `doc-updater`.
- *Speculative (1+)* — `e2e-runner` (no Playwright in tree), `harness-optimizer`,
  `loop-operator`, `build-error-resolver` (generic where value was per-language).

**Cherry-pick, do not admit**: `architect` → into `reviewer.md`.

**Rationale**: each agent ships to three CLIs (inlined into Codex + Gemini
artifacts, symlinked into `.claude/`), dilutes delegation routing, and — under
Q1(A) — carries permanent hand-maintenance debt. Language agents for unused
languages can be added on demand in minutes from a repo already on disk.

---

## Q3 — Sequencing: **(A) Fix adapters first, then port**

### Finding: the Codex agent adapter targets a path Codex never reads

- `strings` on `codex` 0.139.0: **zero** references to `codex/agents`.
- The real surface is **skill-embedded**: `<skill_dir>/agents/openai.yaml`,
  confirmed against five files OpenAI ships under
  `~/.codex/skills/.system/*/agents/openai.yaml`.
- `~/.codex/skills/.system/review-agent/` is a working reference
  implementation of a read-only reviewer subagent.
- Codex `multi_agent` feature flag = **stable/true**; `spawn_agent`,
  `wait_agent`, `close_agent` exist as runtime tools. Delegation works — via
  skills, not an agents directory.

### Real `openai.yaml` schema

```yaml
interface:    { display_name, short_description, default_prompt, icon_small, icon_large }
policy:       { allow_implicit_invocation }
dependencies: { tools: [{ type: mcp, value, description, transport, url }] }
```

There is **no `model:` field** and **no Claude-style `tools:` list**.
`dependencies.tools` declares *MCP servers*, not `Read`/`Grep`/`Glob`.
The system prompt lives in the sibling **`SKILL.md` body**; `default_prompt`
is only a one-line invocation hint.

### Consequences

1. **Model tiering is unrepresentable on Codex — permanently.** The
   `researcher`=haiku / `reviewer`=opus split is a Claude-only optimization.
   On Codex every agent runs the session model. Not a bug; document it so it
   is not re-litigated.
2. Current `_agent_md_to_codex_yaml` (codex.sh:92-129) hardcodes
   `model: gpt-5-codex` and `tools: []`, parses `body` at line 113 and never
   writes it. Every generated file is name + description with **no prompt**,
   while its description still advertises 「Opus，成本高」.
3. `tasks.md:350-351` ("deferred") and `:362` ("mechanism in place; tested via
   dry-run") are **both false** — both CLIs are installed
   (`/opt/homebrew/bin/{codex,gemini}`) and have already been written to.
   Dry-run counts files; it never inspects content.

### Fix plan (in order)

1. **Gemini one-liner** — `_agent_md_to_gemini_skill` (gemini.sh:144-146)
   interpolates `description` into a `"`-quoted YAML scalar with no escaping.
   Safe only because the current 9 繁中 descriptions contain no `"`. Replace
   with `yaml.dump`.
2. **Delete** `_agent_md_to_codex_yaml` and the `~/.codex/agents/` emitter;
   remove the 9 stale `.yaml` files (no prune rule covers that directory).
3. **Rewrite** Codex agents as skills, mirroring `_agent_md_to_gemini_skill`:
   emit `~/.codex/skills/agent-<name>/SKILL.md` (frontmatter + full body) plus
   `agents/openai.yaml` (`interface.display_name`, `short_description`,
   `default_prompt`; `policy.allow_implicit_invocation: false`).
4. **Prune hazard — must fix with (3).** Codex uses `prune_stale_managed`
   (source-dir comparison), so `agent-*` wrappers — which have no
   `tools/skills/agent-*` source — would be created then deleted on the next
   run. Switch Codex to `prune_stale_managed_by_name` with an allowlist of
   skill names **plus** `agent-<name>`, exactly as gemini.sh:245-259 already
   does.

### Verification gap to close

Existing checks (tasks.md:344-349) prove idempotency and symlink integrity but
never that a generated agent is *semantically* intact. Add a content assertion:
generated agent artifacts must contain the source body.

---

## Q4 — Language policy: **English everywhere (migrate all 14)**

**Decision**: `tools/agents/` becomes uniformly English — the 5 ECC ports keep
their English, and the existing 9 繁中 agents are rewritten into English.

**Verified safe.** `tools/rules/core.md:10` governs **reply language only**
(「使用者使用中文時，YOU MUST 回覆台灣繁體中文」) and says nothing about artifact
language. The `繁體中文優先` line in `CLAUDE.md` is a header banner, not an
enforced constraint. English agent files therefore do **not** breach workspace
policy; prompting in 繁中 still yields 繁中 replies.

**Gains**
- Restores mechanical diff-ability against ECC upstream — recovering what
  Q1(A) otherwise gave up permanently.
- Uniform cross-references: `❌ Architecture decisions (→ reviewer)` reads
  consistently across all 14 files.
- Matches the vocabulary of the tools themselves (`Read`, `Grep`,
  `PostToolUse`) and is portable to collaborators.
- Inverts the cost of the 5 ports to ~zero (they are already English).

**Costs**
- Migration of 9 existing files. Mitigated: `code-reviewer.md`,
  `security-reviewer.md`, `reviewer.md` are already being edited for Q1
  cherry-picks, so only 6 are net-new work.
- Loses the literal 繁中 觸發詞 in descriptions (e.g. 「幫我 review 這段程式碼」).
  This is a routing *degradation*, not a break — cross-lingual matching is
  competent, but trigger phrases should be rewritten as natural English
  equivalents rather than translated word-for-word.

**Field-level rules**
| Field | Language |
|---|---|
| `name:` | ASCII (path component + `spawn_agent` identifier) |
| `description:` | English, with natural English trigger phrases |
| body / `SKILL.md` | English |
| `openai.yaml` `interface.*` | English |
| code blocks | verbatim — never translate comments inside security examples |

---

## Q5 — Model tiers: **(C) accept ECC defaults**

| Agent | Tier |
|---|---|
| `planner` | **opus** |
| `tdd-guide` | sonnet |
| `refactor-cleaner` | sonnet |
| `typescript-reviewer` | sonnet |
| `python-reviewer` | sonnet |

Resulting spread across 13 agents (14 minus `architect`, folded into
`reviewer`): **4 haiku / 7 sonnet / 2 opus**.

Rationale for overriding the one-Opus pyramid: planning is the highest-leverage
step in the workflow, and a bad plan costs more than the token delta.

### Consequence — `planner` / `reviewer` boundary must be explicit

Two Opus agents with overlapping scope reintroduces the routing ambiguity that
Q1(A) exists to prevent: `reviewer`'s current description already claims
「架構怎麼設計比較好」/「這個技術選型對嗎」, which is a planner's core question.
Both files are open under Q1(A) (`planner` is hand-authored; `reviewer` is
edited for the `architect` cherry-pick), so the boundary is written at the same
time as the files.

**Split on prospective vs. evaluative:**

| | `planner` (opus) | `reviewer` (opus) |
|---|---|---|
| Owns | Building a plan that does not exist yet: decomposition, phases, sequencing, dependencies, risk identification | Judging something that already exists: a proposed design, tech choice, written plan, architecture |
| Trigger | "how should I build X" | "is this design right" / "which option should I pick" |
| Output | Ordered plan with phases | Analysis + risk list + recommendation |
| Negative scope | ❌ Verdicts on existing architecture (→ reviewer) | ❌ Producing an implementation plan (→ planner) |

Rejected alternative: splitting on *breadth* (feature-scale vs system-scale).
"How big is this" is a judgment made at delegation time with the least
information available; "does this thing exist yet" is a fact.

**Caveat**: this tiering is Claude-only. Per Q3, Codex has no per-agent model
field, so `model:` collapses to the session model on two of three CLIs.

---

## Q6 — Batching: **(A) four commits, adapter first**

### Ordering constraint (measured)

- CI (`.github/workflows/ci.yml`) shellchecks `.claude/hooks/*.sh` and
  `scripts/sync-cli-docs.sh` — but **not** `scripts/adapters/*.sh`.
- `scripts/healthcheck.sh:104-163` validates agent frontmatter only under
  `.claude/agents/` (the Claude side). **Nothing validates generated Codex or
  Gemini artifacts** — exactly the gap that let the dead `~/.codex/agents/`
  path pass as "verified".

The adapter rewrite is therefore the only step with no automated safety net,
and it is the step every other artifact is generated through.

| # | Commit | Contents | Verified by |
|---|---|---|---|
| 1 | `fix(adapters)` | Gemini `yaml.dump` escaping; delete `_agent_md_to_codex_yaml` + `~/.codex/agents/` emitter; rewrite Codex agents as skills; switch Codex to `prune_stale_managed_by_name`; remove 9 stale `.yaml` | Diff generated artifacts before/after against the **unchanged 9** agents |
| 2 | `test(healthcheck)` | Assert generated Codex/Gemini agent artifacts contain the source body; extend shellcheck to `scripts/adapters/*.sh` | Run `healthcheck.sh` — it must catch the dead-path class of bug |
| 3 | `refactor(agents)` | Migrate 9 existing agents to English (Q4) | `git diff` shows translation only, no structural change |
| 4 | `feat(agents)` | 5 new agents + 3 cherry-picks + `planner`/`reviewer` boundary + `tasks.md` corrections | Healthcheck + prose review |

### Why this order

- **1 before 3**: rewriting the adapter while sources change language makes a
  broken artifact ambiguous (adapter bug or translation error?). Running it
  against the unchanged 9 makes the diff a clean before/after of *mechanism*.
- **2 before 3**: commits 3 and 4 then land on a net that catches regressions.
  Adding the assertion afterward would only test the final state.
- **`tasks.md` corrections in 4, not 1**: lines 350-351 and 362 are false now,
  but commit 1 makes them true-ish; correcting mid-sequence would describe a
  state that exists for exactly one commit.

### Verification rule

**`--dry-run` is not sufficient for commit 1.** Dry-run counts intended
actions and is precisely the tool that produced the original false confidence.
Verification must be a real run plus reading the generated files.

---

## ⚠️ BLOCKER — verify before starting C1

**All evidence for the Codex-as-skills schema came from *system* skills**
(`~/.codex/skills/.system/*/agents/openai.yaml`). It is **not confirmed** that
Codex honours `agents/openai.yaml` inside a **user** skill at
`~/.codex/skills/<name>/`. If the schema is system-only, the C1 rewrite merely
*moves* the dead path from `~/.codex/agents/` to
`~/.codex/skills/agent-*/agents/openai.yaml` and fixes nothing.

**Attempted and inconclusive (2026-07-22):**
- Created probe `~/.codex/skills/zztestagent/` with `SKILL.md` +
  `agents/openai.yaml`; structurally identical to a discovered skill
  (`grill-me`) apart from the `.workspace-managed` sentinel, which is a
  workspace marker, not a Codex one.
- `codex exec` → **401 Unauthorized**; `codex doctor` confirms no credentials.
  Runtime `spawn_agent` enumeration is therefore unavailable.
- `codex debug prompt-input` (offline) lists user skills — `grill-me`,
  `agent-team`, `debug`, `perf`, `map`, `caveman` all present — but **not** the
  probe. Most likely a cached skill catalogue rather than a schema rejection,
  since the probe was created seconds earlier; not proven either way.
- Binary `strings` shows `.system` only as a path literal for `imagegen`
  scripts, with no `is_system` / `system_skill` gating symbol — weak evidence
  *for* user skills being eligible, but not conclusive.

**To resolve**: run `codex login`, then create the probe again and ask Codex to
enumerate spawnable agents (or restart the app-server so the catalogue
refreshes). Do this **before** writing the C1 rewrite, not after.

---

## Tool grants for the 5 admits (policy)

Q1 established that ECC's `security-reviewer` ships `Write, Edit` where the
workspace version is deliberately read-only. The same decision must be made
explicitly for the admits rather than absorbing ECC defaults:

- **Reviewers stay read-only.** `typescript-reviewer` / `python-reviewer` get
  `Read, Grep, Glob` — drop ECC's `Bash` grant, matching the existing
  `code-reviewer`. A reviewer that can run commands is a different risk class.
- **Mutating agents keep write access where the job requires it.**
  `refactor-cleaner` (`Read, Write, Edit, Bash` — needs `knip`/`depcheck`/
  `ts-prune`) and `tdd-guide` (`Read, Write, Edit, Bash` — writes tests).
- **`planner` stays read-only** (`Read, Grep, Glob`), matching ECC and the
  `reviewer` precedent: it produces plans, not edits.

## Frontmatter format (settle during C3/C4)

Workspace uses `tools: Read, Grep, Glob` (comma-separated string); ECC uses
`tools: ["Read", "Grep", "Glob"]` (YAML list). Both parse, but yield different
Python values in the adapters. **Pick the workspace comma-separated form** and
normalise all 14 files during C3/C4, or the repo ships a hybrid.

---

## Execution checklist

- [ ] **C0** *(blocker)* `codex login`, then re-run the user-skill
      `agents/openai.yaml` discovery probe. C1's design depends on the result.
- [ ] **C1** `fix(adapters)` — Gemini `yaml.dump`; delete Codex agents emitter;
      Codex agents → `~/.codex/skills/agent-<name>/{SKILL.md,agents/openai.yaml}`;
      `prune_stale_managed_by_name` with `agent-<name>` allowlist; rm 9 stale yaml
- [ ] **C2** `test(healthcheck)` — generated-artifact body assertion; shellcheck `scripts/adapters/*.sh`
- [ ] **C3** `refactor(agents)` — migrate 9 existing agents to English
- [ ] **C4** `feat(agents)` — add `planner`(opus), `tdd-guide`, `refactor-cleaner`,
      `typescript-reviewer`, `python-reviewer` (sonnet); cherry-pick ECC content into
      `code-reviewer.md`, `security-reviewer.md`, `reviewer.md`(+`architect`);
      write `planner`/`reviewer` negative scope; fix `tasks.md:350-351,362`

Per `core.md`, run `/deep-review` before each commit.
