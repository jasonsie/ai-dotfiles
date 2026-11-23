# Third-party notices

This repository is MIT licensed ([LICENSE](LICENSE)). The material below comes from other
authors and keeps its own license. Full license texts are in [LICENSES/](LICENSES/).

## Skills adapted from other repositories

Each folder keeps the author's LICENSE file. The obra/superpowers sections sit in folders from
mattpocock/skills, so their copyright line is in the table below and their license text in
[LICENSES/MIT.txt](LICENSES/MIT.txt). `skills/skills.lock` records the source path, the pinned
commit and the local edits for every one of them.

| Skills | Source | License | Copyright |
|---|---|---|---|
| `codebase-design`, `diagnosing-bugs`, `domain-modeling`, `grill-with-docs`, `grilling`, `handoff`, `implement`, `implement-spec`, `improve-codebase-architecture`, `migrate-to-shoehorn`, `pr`, `prototype`, `research`, `retro`, `setup-agent-skills`, `setup-pre-commit`, `spec-review`, `tdd`, `teach`, `to-questionnaire`, `to-spec`, `to-tickets`, `triage`, `wait-what`, `wayfinder`, `which-skill`, `wizard`, `writing-for-agents` | [mattpocock/skills](https://github.com/mattpocock/skills) | MIT | (c) 2026 Matt Pocock |
| `onboard` | [affaan-m/ECC](https://github.com/affaan-m/ECC) | MIT | (c) 2026 Affaan Mustafa |
| `implement`, `implement-spec`, `writing-for-agents` (adapted sections) | [obra/superpowers](https://github.com/obra/superpowers) | MIT | (c) 2025 Jesse Vincent |

`skills/pr/CREDITS.md` carries that skill's own credits.

## Repository origin

This repository started in 2026 as a fork of
[zeuikli/claude-code-workspace](https://github.com/zeuikli/claude-code-workspace), whose
README states the MIT License. Its files were replaced over time; none remain in the current
tree. Early commits in the history still contain copies of them under that license.

## Documentation mirrors in `docs/upstream/`

`scripts/upstream/sync-upstream.py` copies these sources verbatim. Every mirrored page begins
with a `> Source:` line naming the original URL and, for GitHub sources, a `> License:` line.
Mirrored files keep their source's license; the MIT license of this repository does not
cover them.

### Open-licensed sources

| Folder | Source | License | Notes |
|---|---|---|---|
| `pi/` | [earendil-works/pi](https://github.com/earendil-works/pi), `packages/coding-agent/docs` | MIT | Copyright (c) 2025 Mario Zechner |
| `google/styleguide/` | [google/styleguide](https://github.com/google/styleguide) | CC-BY-3.0 (guides), Apache-2.0 (code samples and editor configs) | Copyright Google LLC. Pages converted from HTML are adaptations; the conversion is the only change. |
| `google/eng-practices/` | [google/eng-practices](https://github.com/google/eng-practices) | CC-BY-3.0 | Copyright Google LLC |
| `google/swift/` | [google/swift](https://github.com/google/swift) | Apache-2.0 | Copyright Google LLC and the Swift project authors |
| `google/opendocs/` | [google/opendocs](https://github.com/google/opendocs) | CC-BY-4.0 | Copyright Google LLC |
| `facebook/folly/`, `facebook/fbthrift/`, `facebook/buck2/` | github.com/facebook/{folly,fbthrift,buck2} | Apache-2.0 | Copyright Meta Platforms, Inc. and affiliates |
| `facebook/hermes/`, `facebook/docusaurus/`, `facebook/astryx/`, `facebook/flipper/` | github.com/facebook/{hermes,docusaurus,astryx,flipper} | MIT | Copyright Meta Platforms, Inc. and affiliates |
| `facebook/fboss/` | [facebook/fboss](https://github.com/facebook/fboss) | BSD-3-Clause | Copyright (c) 2013-2015, Facebook, Inc. |
| `facebook/sapling/`, `facebook/bpfilter/` | github.com/facebook/{sapling,bpfilter} | GPL-2.0 | These files stay under the GPL-2.0, reproduced in [LICENSES/GPL-2.0-only.txt](LICENSES/GPL-2.0-only.txt). They are mirrored verbatim and are not combined with other code in this repository. |
| `facebook/hhvm/` | [facebook/hhvm](https://github.com/facebook/hhvm) | PHP-3.01 and Zend-2.0 | This product includes PHP software, freely available from <http://www.php.net/software/>. |

### Sources without an open license

| Folder | Source | Terms |
|---|---|---|
| `claude/` | [code.claude.com/docs](https://code.claude.com/docs) | © Anthropic PBC. All rights reserved; no redistribution license published. |
| `codex/` | [learn.chatgpt.com/docs](https://learn.chatgpt.com/docs) | © OpenAI. No redistribution license published; OpenAI Terms of Use apply. |
| `antigravity/` | [antigravity.google/docs](https://antigravity.google/docs) | © Google LLC. No open-content license notice found; Google Terms of Service apply. |

These three mirrors exist so that agents can look up a CLI's current documentation offline.
They are reference copies of public pages, unchanged except for the header line, and are
not relicensed by this repository. The rights holders may ask for their removal at any time.
