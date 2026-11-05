# Plugins in every CLI: design record

Working record of the `grill-with-docs` interview, started 2026-11-05. Resume from **Open**.
Once built, fold it into `docs/how-it-works.md` and delete this file.

Goal: the plugins `zkfy` and `web-clipper` work in Claude Code, Codex, Pi and Antigravity, set
up by ai-dotfiles from one list.

Model (user): npm's `install` and `uninstall`, nothing more. A packaging question starts from how
those two behave; the rest of npm (`ls`, `outdated`, `prune`, `engines`) is out of scope.

## Facts: trial installs, 2026-11-05

Each CLI installed both plugins from their checkouts into a throwaway home folder
(`CODEX_HOME`, `HOME`, `PI_CODING_AGENT_DIR`); real configs untouched.

| | Install | Skills | Commands (5) | Agents (8) | Hooks (2) | MCP `notion` | `web-clipper` on PATH |
|---|---|---|---|---|---|---|---|
| Claude Code 2.1.318 | marketplace, added by hand outside ai-dotfiles | yes | yes | yes | yes | yes | yes, plugin `bin/` |
| Codex 0.166 | `codex plugin marketplace add`, then `codex plugin add`; reads the Claude format as is | 8 of 8, as `zkfy:<skill>` | no | no | per docs; needs `/hooks` trust | yes | no |
| Antigravity 1.4.4 | `agy plugin install <dir or GitHub URL>`; converts the Claude format | yes | turned into skills `zkfy-cmd-*` | copied | broken: Claude file copied as is | broken: URL dropped | no |
| Pi 1.0.2 | no plugins; `pi install <path or git>` adds a package | 6 of 8 | no (wants `prompts/`) | no subagents | no (wants an extension) | no | no |

- Pi drops `zk-note` and `vault-reorg`: their frontmatter is not strict YAML.
- About 20 lines of zkfy skill and command text use `${CLAUDE_PLUGIN_ROOT}`. Only Claude fills it
  in; Codex sets it for hook commands only.
- Codex and Antigravity also read the portable Agent Plugins format (a root `plugin.json`). Pi
  reads a `pi` key in `package.json`.
- Every CLI installs an exact git tag itself (each tried with `web-clipper--v2.1.0`, which
  installed 2.1.0):
  - Claude: `claude plugin marketplace add 'jasonsie/web-clipper#web-clipper--v2.1.0'`; it also
    writes the marketplace into `~/.claude/settings.json` (`extraKnownMarketplaces`).
  - Codex: `codex plugin marketplace add jasonsie/web-clipper --ref web-clipper--v2.1.0`.
  - Antigravity: `agy plugin install https://github.com/jasonsie/web-clipper/tree/web-clipper--v2.1.0`;
    a `#ref` suffix is ignored and installs the latest.
  - Pi: `pi install git:github.com/jasonsie/web-clipper@web-clipper--v2.1.0`, checked out under
    `~/.pi/agent/git/github.com/jasonsie/web-clipper`.
- Release tags (`<name>--v<version>`, made by `claude plugin tag --push`): web-clipper has
  `--v2.1.0` and `--v2.2.0`. zkfy has none, only `archive/*` tags; its `main` is at 1.6.0.
- Claude came by web-clipper as zkfy's dependency (`^2.1`, resolved against the release tags), so
  it reports the version with a commit suffix: `2.2.0-b1f6b17dca62`.
- Moving an installed plugin to a new tag (each tried 2.1.0 to 2.2.0; a plugin the user disabled
  stays disabled):
  - Claude: a second `marketplace add` with a new ref is refused while `extraKnownMarketplaces`
    names the old one; removing the marketplace uninstalls the plugin and deletes its saved data.
    Works: set the new ref in `extraKnownMarketplaces`, run
    `claude plugin marketplace add '<repo>#<tag>'`, then `claude plugin update <plugin>@<marketplace>`.
  - Codex: a second `marketplace add` with a new ref is refused; removing it uninstalls. Works: set
    `ref` under `[marketplaces.<name>]` in `config.toml`, then `codex plugin marketplace upgrade
    <name>`, which also refreshes the installed plugin. Another `codex plugin add` re-enables a
    disabled plugin.
  - Antigravity: `agy plugin install <repo URL>/tree/<new tag>` replaces the install.
  - Pi: `pi install git:github.com/<repo>@<new tag>` replaces the entry and moves the checkout.
- zkfy 1.6.0 requires web-clipper `^2.2` (Claude's `dependencies`). Claude installs it from the
  highest matching tag; Codex and Antigravity ignore the dependency (tried: only zkfy installed);
  Pi has no dependencies.
- Claude's auto-update moves a constrained dependency to the highest tag that satisfies every
  range, past a marketplace's pinned ref. Both marketplaces have auto-update on today.
- Only Claude puts a plugin's `bin/` on its shell PATH, after the user's own entries. Codex and
  Antigravity document nothing similar. `bin/web-clipper` finds `clip.py` through its resolved
  path, so it runs through a symlink.
- The validators catch different things. `claude plugin validate` flags one zkfy agent's broken
  YAML (`conceptual-modeler-agent`) but not the two skills Pi drops. `agy plugin validate
  --strict`, given a native manifest, skips all 8 zkfy agents (`model: sonnet` is not an
  Antigravity tier, and that one agent's YAML is broken) and loads only the first 24000 bytes of a
  skill body (`vault-lint` has 25153). Codex and Pi have no validator.

## Decisions

1. **ai-dotfiles owns distribution only.** A `plugins` step installs, enables and checks each
   listed plugin through each CLI's own plugin manager. Each plugin repo makes its own content
   portable; a missing CLI feature is documented, never shimmed. Why: the repo's "shared
   behavior, native differences" rule; install-time adapters would tie this repo to plugin
   internals.
2. **Plugin versions live in the ai-dotfiles config, like `package.json`;** each CLI installs
   exactly the recorded version. Why (user): one reviewed place decides what runs, on every Mac
   and in every CLI. Each CLI fetches that version from GitHub itself: all four pin a tag
   natively, so a shared checkout is not needed for consistency (reopen if one is wanted).
3. **An exact version per plugin, no lock file.** `"version": "2.2.0"` installs the release tag
   `web-clipper--v2.2.0` in every CLI. A bump is a reviewed one-line edit. Why: the same result
   on every Mac and CLI with the least code, like
   the exact pins in `skills/skills.lock`; a range needs a resolver and a lock, too much for two
   plugins their owner releases. Accepted: no automatic patch releases; a moved tag goes
   unnoticed.
4. **The list is `config/plugins.json`, keyed by plugin name, checked strictly like
   `ai-clis.json`.** Each entry has `source` (a GitHub repo whose root is the plugin), `version`
   (exact) and `targets` (a required list of CLIs). The marketplace name is read from the repo at
   install, not restated. It covers listed plugins only; any other plugin in any CLI is the
   user's and stays as it is. Why: the style of the other config files, with room for later
   fields.
5. **Release tags are always `<name>--v<version>`, made by `claude plugin tag --push`.** Before
   installing, the plugins step checks the tag exists on GitHub; a missing tag stops the run and
   prints that command. zkfy tags 1.6.0 once (a plugin-repo fix). Why: Claude's own convention, which
   its dependency resolution reads and web-clipper already follows.
6. **A changed pin reaches each CLI on the next `ai-dotfiles install`; nothing proposes one.** The
   step moves each CLI with the sequences under Facts, keeping a plugin the user disabled
   disabled; for Claude and Codex it edits one key in a file the CLI owns, backed up, as
   `settings.py` does. The owner releases both plugins and edits the pin at release. Why (user):
   no code for a weekly report or an `outdated` command. Accepted: a forgotten bump leaves every
   CLI on the old version, unnoticed.
7. **Every plugin is listed with its own pin, dependencies included, and checked at install.**
   Before installing, the step reads each
   plugin's `plugin.json` at its tag and stops when a dependency is unlisted, goes to fewer CLIs,
   or is pinned outside the range (`^`, `~`, exact). Claude's managed marketplaces get
   `autoUpdate: false`, so only ai-dotfiles moves versions. Why: every CLI that gets zkfy gets
   web-clipper, Claude finds the dependency already met, and a bad pair fails at install rather
   than at run time.
8. **Plugin commands go on PATH the way an npm global install does.** For each listed plugin with
   a `bin/` folder, the step keeps one checkout at the pinned tag in
   `~/.local/share/ai-dotfiles/plugins/<name>` and links each `bin/` file into `~/.local/bin`; a
   name something else owns is refused. Why: every CLI and the shell run the same pinned
   command, whichever CLIs are on; Claude's own plugin `bin/` comes after `~/.local/bin`, at the
   same version.
9. **A gap is filled with the CLI's own feature where one exists, else documented.** Plugins turn
   commands into skills; give Antigravity its own `hooks.json` and `mcp_config.json` (with
   `.antigravity-plugin/plugin.json`, so it loads as is, unconverted); give Pi an extension for
   hooks and MCP; a subagent step says what to do without one (Pi). Each plugin's README carries
   a per-CLI support table. ai-dotfiles installs wherever `targets` says; no `engines` check.
   Why: the rule this repo follows for itself (Pi gets its hooks through `agent_hooks.ts`); full
   function wherever a CLI allows it.
10. **The list controls only the plugins it names.** Dropping a plugin, or a CLI from its
    `targets`, removes it there on the next install, only where the receipt says ai-dotfiles
    installed it (like `npm uninstall`). A plugin already installed when first listed is taken over:
    moved to the pin, recorded as found, and left installed when dropped. Switching a CLI off,
    or `ai-dotfiles uninstall`, leaves plugins, PATH links and checkouts in place and lists them,
    like MCP servers. Why: the config is the truth for what it names, plugins the user installed
    never vanish, and MCP servers and settings already work this way. Accepted: removing
    everything takes emptying the list first.
11. **`ai-dotfiles check` needs nothing plugin-specific.** The plugins step is idempotent, so its
    dry run reports a missing plugin, a wrong version or a plugin to remove as pending changes,
    which the check already fails on; a plugin the user disabled is not a change. Why (user):
    npm's install and uninstall are enough; no `ls`-style report or version probe.
12. **Adding, bumping or removing a plugin is a hand edit of `config/plugins.json`, applied by
    `ai-dotfiles install`;** `ai-dotfiles uninstall` stays as it is; no new commands. Why: every
    config file here works this way, plugins change rarely, and at release the owner has just
    made the tag.
13. **The portability rules live in a new skill here, `portable-plugin`, linked into every CLI.**
    The rules: release tags; strict-YAML frontmatter; paths relative to the skill folder, never
    `${CLAUDE_PLUGIN_ROOT}`; commands as skills; other skills cited by bare name (the `zkfy:`
    prefix exists only in Claude and Codex); PATH commands in `bin/`; for Antigravity its own
    manifest, `hooks.json`, `mcp_config.json`, model tiers and the 24000-byte skill body; for Pi
    an extension for hooks and MCP; subagent steps that say what to do without one; a README
    support table. The check: `claude plugin validate`, `agy plugin validate --strict`, then a
    trial `ai-dotfiles install`, with the Codex and Pi checks written as steps. zkfy's and
    web-clipper's `AGENTS.md` name the skill. Why: rules that apply in some repos load on demand
    from a skill, as everywhere in this repo; one source for every plugin. Costs one
    `which-skill` line, which a test checks.
14. **Ship by readiness.** First the ai-dotfiles side, with web-clipper 2.2.0 for all four CLIs
    and zkfy 1.6.0 for Claude only (once tagged); then zkfy's fixes in its repo, a release, and
    its pin bumped with `codex`, `pi` and `agy` added to its targets. Why: each CLI gets only
    what works; outside Claude, zkfy's commands, `${CLAUDE_PLUGIN_ROOT}` paths, Antigravity hooks
    and MCP, and two Pi skills are broken today. Accepted: zkfy reaches Codex, Antigravity and Pi
    only with its portable release.

## Terms

- **Plugin:** an installable bundle (skills, commands, agents, hooks, MCP servers, commands for
  PATH) kept in its own GitHub repo. Here: one listed in `config/plugins.json`.
- **Pin:** a plugin's exact version in `config/plugins.json`. Every CLI runs that version.
- **Release tag:** the git tag `<name>--v<version>` that marks a plugin release; a pin installs it.
- **Taken over:** a listed plugin that was already installed when first listed. It is moved to
  the pin like any other, but never removed.
- **Gap:** a plugin feature a CLI cannot load as shipped. Filled with the CLI's own feature where
  one exists, else documented.

## Work, in order

ai-dotfiles, this repo:

1. `config/plugins.json`: web-clipper 2.2.0 for all four CLIs; zkfy 1.6.0 for Claude, once
   `zkfy--v1.6.0` exists.
2. The plugins step: the strict config check, the tag check, the dependency check; install, move
   and remove per CLI with the sequences under Facts; `autoUpdate: false` on Claude's managed
   marketplaces; a receipt that tells installed from taken over; the PATH checkouts and links;
   dry run; uninstall lists what stays. Wired into `install.sh` and `uninstall.sh`; unit tests
   with fake CLIs. Try first: taking over `zkfy-marketplace`, which Claude has from a git URL,
   not in `extraKnownMarketplaces`.
3. `skills/portable-plugin/` and its `which-skill` line.
4. `skills/tutor/`: cite zkfy's `query` skill by its bare name.
5. Fold this record into `docs/how-it-works.md` (flow, CLI table, backups table, glossary), add
   the map rows in `AGENTS.md` and a line in `README.md`, then delete this file.

zkfy, its repo:

1. Tag 1.6.0 now: `claude plugin tag --push` at `3fc426b`.
2. Meet `portable-plugin`: strict YAML (`zk-note`, `vault-reorg`, `conceptual-modeler-agent`);
   paths relative to the skill folder; commands as skills; agents Antigravity can load (or read
   as plain files); Antigravity's manifest, `hooks.json` and `mcp_config.json`; a Pi extension for
   the hooks and `notion`; subagent steps that work without one; `vault-lint` under 24000 bytes;
   a README support table; `AGENTS.md` names the skill.
3. Release, then here: bump zkfy's pin and add `codex`, `pi` and `agy` to its targets.

web-clipper, its repo: `AGENTS.md` names `portable-plugin` in place of "Claude-only for now"; a
README support table and install through ai-dotfiles.

Proposed, to confirm: each plugin's release steps end with bumping its pin here.

## Open

None. Every branch is settled; the user confirmed the summary on 2026-11-05 and chose `to-spec`
and `to-tickets` next. Still to confirm: the release-step proposal under Work.
