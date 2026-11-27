#!/usr/bin/env python3
"""What a cloud session on this repo gets at start: `cloud_session.py start`, a SessionStart hook.

A cloud session runs on a fresh VM that reads only the clone, so what a Mac gets from
`ai-dotfiles install` never reaches it. In a cloud session (CLAUDE_CODE_REMOTE=true), `start`:
- returns the global rules (config/global-agents.md, which a Mac links as ~/.claude/CLAUDE.md) as
  the session's additionalContext;
- links each skill that config/cloud.json does not keep local into .claude/skills/ (relative links
  into skills/, which .gitignore keeps out of git) and, when it made one, asks for reloadSkills,
  since skill discovery ran before the hook;
- puts the repo's scripts/ first on the PATH of the commands Claude runs, through the file
  CLAUDE_ENV_FILE names, once, so `ai-dotfiles` runs.
Anywhere else it does nothing: on a Mac the user-level setup already does all three, and links
committed or made there would list every skill again in each linked worktree. The repo is the
session's project folder, CLAUDE_PROJECT_DIR (this script's repo when that is unset).

.claude/settings.json runs it only when CLAUDE_CODE_REMOTE is true, so a Mac session never
starts Python for it. It fails open and says so: a part that fails becomes a line of the context
naming what is missing, and the exit is always 0. It builds Claude Code's hookSpecificOutput
itself: scripts/agent_hooks.py has no SessionStart kind, and a cloud session is always Claude
Code. Standard library only; reads no network.
"""
import json
import os
from pathlib import Path
import shlex
import sys


def project():
    return Path(os.environ.get('CLAUDE_PROJECT_DIR') or Path(__file__).resolve().parents[1])


def rules(root):
    """The global rules, as context."""
    text = (root / 'config/global-agents.md').read_text().strip()
    return ('These are your global rules from ai-dotfiles (config/global-agents.md), which a Mac '
            f'loads as ~/.claude/CLAUDE.md. Follow them in this session.\n\n{text}')


def link_skills(root):
    """Link each skill config/cloud.json does not keep local into <root>/.claude/skills/, as a
    relative link; an entry already there is left alone. Returns how many links it made."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib/install'))
    import skills as skill_folders  # lib/install/skills.py: the repo's skill discovery

    folder = root / '.claude/skills'
    folder.mkdir(parents=True, exist_ok=True)
    made = 0
    for name, source in sorted(skill_folders.cloud_skills(root).items()):
        link = folder / name
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(os.path.relpath(source, folder))
        made += 1
    return made


def put_on_path(env_file, scripts):
    """Append the line that puts `scripts` first on PATH to the session's env file, once."""
    env = Path(env_file)
    line = f'export PATH={shlex.quote(str(scripts))}:"$PATH"\n'
    if env.is_file() and line in env.read_text():
        return
    with env.open('a') as out:
        out.write(line)


def start():
    """The SessionStart reply for a cloud session; None anywhere else."""
    if os.environ.get('CLAUDE_CODE_REMOTE') != 'true':
        return None
    root, lines = project(), []
    try:
        lines.append(rules(root))
    except OSError as error:
        lines.append(f'The global rules (config/global-agents.md) could not be read: {error}.')
    made = 0
    try:
        made = link_skills(root)
    except (OSError, ValueError, KeyError, ImportError) as error:
        lines.append(f"The repo's skills could not be linked into .claude/skills/ ({error}); "
                     'read one as <skills or features>/<name>/SKILL.md.')
    try:
        env_file = os.environ.get('CLAUDE_ENV_FILE')
        if not env_file:
            raise OSError('CLAUDE_ENV_FILE is not set')
        put_on_path(env_file, root / 'scripts')
    except OSError as error:
        lines.append(f'scripts/ is not on PATH ({error}); run ai-dotfiles as {root / "scripts/ai-dotfiles"}.')
    reply: dict = {'hookEventName': 'SessionStart', 'additionalContext': '\n\n'.join(lines)}
    if made:
        reply['reloadSkills'] = True
    return reply


def main(argv):
    if argv[1:] != ['start']:
        print('usage: cloud_session.py start', file=sys.stderr)
        return 0
    try:
        reply = start()
    except Exception as error:  # never fail a session over its context; say what broke
        reply = {'hookEventName': 'SessionStart', 'additionalContext': f'scripts/cloud_session.py failed: {error!r}'}
    if reply:
        try:
            print(json.dumps({'hookSpecificOutput': reply}))
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
