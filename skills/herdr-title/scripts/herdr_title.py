#!/usr/bin/env python3
"""herdr-title: an agent's row in Herdr's sidebar says what its current prompt is for.

  herdr-title hook prompt --cli (claude|codex|pi)   JSON in; nothing out
  herdr-title hook end --cli (claude|codex|pi)      JSON in; nothing out
  herdr-title classify                              the model's turn for one prompt; the hook starts it

Each time the user submits a prompt, the hook picks one tag for it and reports the tag to
Herdr as the pane's state labels: `[GRILLING]` while the agent works, `[GRILLED]` once it is
the user's move, `[BLOCKED]` at a permission dialog. Herdr switches between them from the
state it detects itself and draws the label next to the tab's name.

Who picks the tag:
- A prompt that is a command word (`approve`, `approve 57`) or names a skill (`/grilling`,
  `$tutor`, `/zkfy:zk-note`) is tagged at once, by the hook.
- Any other prompt goes to a small model, in a process the hook starts and does not wait for
  (`classify`): a headless `claude -p` that gets the session's current tag, the end of the
  agent's last message and the prompt, and answers with one tag or KEEP. The tag lands about
  three seconds later. Half the prompts are short answers ("1", "y") whose purpose is in the
  question they answer, which is why the model sees the agent's last message.
- A prompt the user did not type (a subagent's report, another session's message) leaves the
  tag as it is. So does a model that says KEEP, fails, or answers after a newer prompt, and so
  does every hook call from inside a subagent or teammate, which shares the pane.
When the session ends the tag comes off. The tags, the command words, the skills and the
model's instruction are config/herdr-title.json's. The CLIs' hook formats live in the repo's
scripts/agent_hooks.py, their transcripts in scripts/agent_sessions.py.

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
KEEP = 'KEEP'  # the model's word for "this prompt changes nothing"
# What the model reads: the end of the agent's last message, where its question is; a long
# prompt's start and end, since a pasted log sits between the request and the question about it.
REPLY_END = 800
PROMPT_START, PROMPT_END = 500, 300


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


def ask_later(request):
    """Hand the prompt to `classify` in a process of its own and return: the model takes
    seconds, and the user's prompt must not wait for it."""
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'classify'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    with contextlib.suppress(OSError):
        child.stdin.write(json.dumps(request).encode())
        child.stdin.close()


def on_prompt(event, state):
    settings = config()
    # A subagent or teammate shares the lead's pane, and its prompts are not the user's.
    if event.subagent or not typed(event.prompt, settings):
        return
    seq = time.time_ns()
    tag = certain(event.prompt, settings)
    if tag:
        state.update(tag=tag, seq=seq)
        report(pane(), tag, seq, settings)
    else:
        ask_later({'cli': event.cli, 'session': event.session, 'pane': pane(), 'prompt': event.prompt,
                   'transcript': event.transcript, 'seq': seq})


def ask(settings, current, said, prompt):
    """The tag a small model gives the prompt, or None when it names none. It gets the session's
    current tag, the end of the agent's last message and the prompt, through a headless
    `claude -p` that loads no user settings (so no hooks, plugins or MCP servers), saves no
    session, has no tools and cannot see the pane."""
    claude = shutil.which('claude')
    if not claude:
        return None
    model = settings['model']
    listed = '\n'.join(f'{tag}: {forms["means"]}' for tag, forms in settings['tags'].items())
    question = (f"Current label: {current or 'none'}\n\nThe agent's last message ended:\n{said or '(none)'}\n\n"
                f"The user's new prompt:\n{prompt}")
    folder = SESSIONS.folder / 'model'  # a folder without project settings of its own
    folder.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([claude, '-p', question, '--model', model['name'], '--tools', '',
                          '--no-session-persistence', '--setting-sources', 'project', '--strict-mcp-config',
                          '--system-prompt', '\n'.join(model['ask']).replace('{tags}', listed)],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=model['timeout'], cwd=folder,
                         env={key: value for key, value in os.environ.items() if not key.startswith('HERDR_')})
    words = re.findall(r'[A-Z]+', run.stdout.upper()) if run.returncode == 0 else []
    word = next((word for word in words if word in settings['tags'] or word == KEEP), None)
    return None if word == KEEP else word


def classify(request):
    """The model's turn for one prompt: ask, then tag the pane with its answer."""
    import agent_sessions  # the CLIs' transcripts; not needed by the hook itself
    settings, session = config(), request['session']
    said = agent_sessions.last_reply(request['cli'], request['transcript']) if request.get('transcript') else ''
    prompt = request['prompt']
    if len(prompt) > PROMPT_START + PROMPT_END:
        prompt = f'{prompt[:PROMPT_START]}\n[...]\n{prompt[-PROMPT_END:]}'
    tag = ask(settings, SESSIONS.load(session).get('tag'), said[-REPLY_END:], prompt)
    state = SESSIONS.load(session)  # read again: a newer prompt may have been tagged while the model thought
    if tag and state.get('seq', 0) <= request['seq']:
        SESSIONS.save(session, {**state, 'tag': tag, 'seq': request['seq']})
        report(request['pane'], tag, request['seq'], settings)


def cmd_classify(_args):
    with contextlib.suppress(Exception):  # nobody is listening: a failure leaves the tag as it is
        classify(json.loads(sys.stdin.read()))
    return 0


def on_end(event):
    """The session is over: its tag comes off the pane, and its state file goes. A subagent's
    or teammate's end is not the pane's."""
    if event.subagent:
        return
    herdr('pane', 'report-metadata', pane(), '--source', SOURCE, '--clear-state-labels', '--seq', str(time.time_ns()))
    if event.session:
        SESSIONS.file(event.session).unlink(missing_ok=True)


def cmd_hook(args):
    if not pane():
        return 0
    if args.kind == 'end':
        return agent_hooks.serve(args.cli, 'end', lambda data: on_end(agent_hooks.read(args.cli, 'end', data)))
    return agent_hooks.serve(args.cli, args.kind,
                             lambda data: agent_hooks.call(args.cli, args.kind, data, on_prompt, SESSIONS))


def parser():
    top = argparse.ArgumentParser(prog='herdr-title', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    hook = sub.add_parser('hook', help='the CLI hook: JSON on stdin')
    hook.add_argument('kind', choices=('prompt', 'end'))
    hook.add_argument('--cli', choices=CLIS, required=True)
    hook.set_defaults(run=cmd_hook)
    sub.add_parser('classify', help="the model's turn: a request as JSON on stdin (the hook starts it)"
                   ).set_defaults(run=cmd_classify)
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
