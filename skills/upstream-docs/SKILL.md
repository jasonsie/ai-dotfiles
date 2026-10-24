---
name: upstream-docs
description: Look a rule up in the mirrored upstream docs instead of guessing. Holds Google's and Meta's coding-style guides (C++, Python, Go, Java, JavaScript, TypeScript, Shell, Swift, Rust, Objective-C, C#, HTML/CSS, Markdown), Google's code review guide, Google's and Meta's docs-writing guides, and the official Claude Code, Codex, Pi and Antigravity docs. Use when a style question comes up while writing or reviewing code, when writing READMEs, docs, commit messages or PR descriptions, when reviewing a PR, or when asked how Claude Code, Codex, Pi or Antigravity is configured (settings, hooks, MCP, skills, permissions, sandbox).
---

# Upstream docs

`docs/upstream/` in the ai-dotfiles repo holds machine-written mirrors, one folder per source
(`claude`, `codex`, `pi`, `antigravity`, `google`, `facebook`; GitHub files at
`<source>/<repo>/<path>`). Each source's `MIRROR-INDEX.json` carries titles, `when` labels
(the task a page serves) and heading outlines with line numbers. `query.py` answers from
those indexes; a page can run to megabytes, so the unit of reading is a section.

1. **Find.** `python3 <this skill folder>/query.py find <terms>`; `--source <id>` narrows,
   `--grep` searches page bodies when titles and headings miss. Done when you hold a
   `source/path` and a heading.
2. **Outline** a long page or an unclear heading: `query.py outline <source/path> [--depth 3]`.
3. **Show** the section: `query.py show <source/path> --heading "<text>"`, or `--lines A-B`;
   `--max-lines` pages through a long one.
4. **Cite** as `source/path#heading`. The page's `> Source:` line is the upstream URL and
   `> License:` the attribution the mirror carries.

`query.py list` names the sources. This folder is `~/.claude/skills/upstream-docs/` in Claude
Code, `~/.agents/skills/upstream-docs/` in Codex and Pi, `~/.gemini/config/skills/upstream-docs/`
in Antigravity. A guide that is missing is added with the `collect-docs` skill; the weekly sync
refreshes every source.
