#!/usr/bin/env python3
"""herdr-title: an agent's row in Herdr's sidebar says what its current prompt is for.

  herdr-title hook prompt --cli (claude|codex|pi)   JSON in; nothing out

Each time the user submits a prompt, the hook picks one tag for it and reports the tag to
Herdr as the pane's state labels: `[GRILLING]` while the agent works, `[GRILLED]` once it is
the user's move, `[BLOCKED]` at a permission dialog. Herdr switches between them from the
state it detects itself and draws the label next to the tab's name. A prompt that is a
command word (`approve`, `approve 57`) or names a skill (`/grilling`, `$tutor`,
`/zkfy:zk-note`) is tagged at once; a prompt the user did not type (a subagent's report,
another session's message) leaves the tag as it is.
The tags, the command words and the skills are config/herdr-title.json's. The CLIs' hook
formats live in the repo's scripts/agent_hooks.py.

Outside a Herdr pane (HERDR_ENV is not 1) nothing runs. A failure never blocks a prompt and
prints nothing: a prompt hook's stdout would reach the model.

State: $HERDR_TITLE_STATE, else ~/.local/state/ai-dotfiles/herdr-title/ (each session's tag).
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SKILL = Path(__file__).resolve().parent.parent
REPO = SKILL.parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats, in the repo's scripts folder)

CONFIG = REPO / 'config' / 'herdr-title.json'
ENV = 'HERDR_TITLE_STATE'
DEFAULT_STATE = '~/.local/state/ai-dotfiles/herdr-title'
KEEP_SECONDS = 7 * 24 * 3600
SESSIONS = agent_hooks.Store(ENV, DEFAULT_STATE, KEEP_SECONDS)
CLIS = ('claude', 'codex', 'pi')  # the CLIs that hand over each prompt
SOURCE = 'user:ai-dotfiles-title'  # who reports, to Herdr; beside Herdr's own integration
HERDR_TIMEOUT = 5
# A skill named in a prompt: /name, $name or /plugin:name, not a piece of a path.
NAMED = re.compile(r'(?<![\w/.:~-])[/$]((?:[a-z][a-z0-9-]*:)?[a-z][a-z0-9-]*)(?![\w/-]|\.\w)')
NUMBERED = re.compile(r'\s+#?\d+$')  # the PR number after a command word


def config():
    return json.loads(CONFIG.read_text())


def pane():
    """This pane's id when the CLI runs in Herdr, else None."""
    return os.environ.get('HERDR_PANE_ID') if os.environ.get('HERDR_ENV') == '1' else None


def certain(prompt, settings):
    """The tag a prompt names outright, or None: the prompt is a command word (with a PR number
    or not: "approve", "Approve #57."), or the first skill in it that has a tag."""
    said = NUMBERED.sub('', prompt.strip().rstrip('.!').lower())
    if said in settings['commands']:
        return settings['commands'][said]
    skills = {**settings['outside'], **settings['skills']}
    for name in NAMED.findall(prompt):
        tag = skills.get(name) or skills.get(name.split(':')[-1])
        if tag:
            return tag
    return None


def labels(tag, settings):
    """Herdr's label for each state it detects: working, the user's move (seen or not), blocked."""
    forms = settings['tags'][tag]
    yours = f"[{forms['done']}]"
    return {'working': f"[{forms['working']}]", 'idle': yours, 'done': yours, 'blocked': f"[{settings['blocked']}]"}


def herdr(*args):
    """Run one herdr command; a Herdr that is missing, slow or unhappy changes nothing."""
    binary = os.environ.get('HERDR_BIN_PATH') or shutil.which('herdr')
    if not binary:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([binary, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=HERDR_TIMEOUT, check=False)


def report(where, tag, seq, settings):
    """Tag the pane. `seq` is when the prompt came: Herdr drops a report older than its last one."""
    pairs = [arg for state, text in labels(tag, settings).items() for arg in ('--state-label', f'{state}={text}')]
    herdr('pane', 'report-metadata', where, '--source', SOURCE, *pairs, '--seq', str(seq))


def typed(prompt, settings):
    """Whether the user wrote this prompt: not empty, and not a report from a subagent, another
    session or the harness, which arrive as prompts too and say nothing about the user's purpose."""
    return bool(prompt.strip()) and not prompt.lstrip().startswith(tuple(settings['machine']))


def on_prompt(event, state):
    settings = config()
    if not typed(event.prompt, settings):
        return
    tag = certain(event.prompt, settings)
    if tag:
        seq = time.time_ns()
        state.update(tag=tag, seq=seq)
        report(pane(), tag, seq, settings)


def cmd_hook(args):
    if not pane():
        return 0
    return agent_hooks.serve(args.cli, args.kind,
                             lambda data: agent_hooks.call(args.cli, args.kind, data, on_prompt, SESSIONS))


def parser():
    top = argparse.ArgumentParser(prog='herdr-title', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    hook = sub.add_parser('hook', help='the CLI hook: JSON on stdin')
    hook.add_argument('kind', choices=('prompt',))
    hook.add_argument('--cli', choices=CLIS, required=True)
    hook.set_defaults(run=cmd_hook)
    return top


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    is_hook = argv[:1] == ['hook']
    try:
        # A bad hook call must stay silent and exit 0: status 2 and stderr would steer the CLI.
        with contextlib.redirect_stderr(io.StringIO() if is_hook else sys.stderr):
            args = parser().parse_args(argv)
    except SystemExit as error:
        return 0 if is_hook else int(error.code or 0)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
