#!/usr/bin/env python3
"""herdr-title: an agent's row in Herdr's sidebar says what its prompt is for and whose move it is.

  herdr-title classify                            a model's turn for one prompt or stop; the hook starts it

The CLIs' hooks reach it through the door (`ai-dotfiles hook`, lib/door.py), which calls hook(event)
at each prompt, stop, error, interrupt, permission dialog, question or plan tool (pre), MCP form,
resume (start) and session end, per CLI as ../feature.json says. Its reply is always none (the
door gives each CLI its quiet reply: Codex's stop wants {}). A cloud session runs none of it:
Herdr, whose rows it labels, runs on the Mac.

The label has three layers, type › status › result: `grill › run` while the agent works,
`grill › wait › ask` when it waits for the user's answer, `› fail` after an error, `› done` once
it finished and nobody has looked, and plain `idle` after a look. The hook keeps a mode per
session and reports one label per state Herdr detects (working, blocked, done, idle, unknown);
Herdr shows the one for the state it sees and draws it in the sidebar.

When a turn ends (stop), the label says ask at once if the reply's last line ends with a
question mark (or a Codex plan block), fail at once after an error or Claude Code's usage-limit
note, and otherwise keeps `run` while a small model reads the end of the reply and answers ask,
wait (its own background work runs on) or done, about three seconds later.

Who picks the type:
- A prompt that is a command word (`approve`, `approve 57`) or names a skill (`/grilling`,
  `$tutor`, `/zkfy:zk-note`) is typed at once, by the hook.
- Any other prompt goes to a small model, in a process the hook starts and does not wait for
  (`classify`): a headless `claude -p` that gets the session's current type, the end of the
  agent's last message and the prompt, and answers with one type or keep. The type lands about
  three seconds later. Half the prompts are short answers ("1", "y") whose purpose is in the
  question they answer, which is why the model sees the agent's last message.
- A prompt the user did not type (a subagent's report, another session's message, a scheduled
  prompt firing) leaves the type as it is. So does a model that says keep, fails, or answers
  after a newer prompt, and so does every hook call from inside a subagent or teammate, which
  shares the pane.
When the session ends the labels and the need token come off. The types, the words, the command
words, the skills and the model's instruction are labels.json's. The CLIs' hook
formats live in the repo's scripts/agent_hooks.py, their transcripts in scripts/agent_sessions.py.

Outside a Herdr pane (HERDR_ENV is not 1) nothing runs. A failure never blocks a prompt and
prints nothing: a prompt hook's stdout would reach the model.

State: $HERDR_TITLE_STATE, else ~/.local/state/ai-dotfiles/herdr-title/ (each session's type and
mode; panes/ holds the session each pane belongs to). A teammate in Claude Code's agent-team tmux
server and a headless `claude -p` started from a pane change nothing: they share its environment.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

SKILL = Path(__file__).resolve().parent.parent
REPO = SKILL.parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats, in the repo's scripts folder)

CONFIG = SKILL / 'labels.json'
ENV = 'HERDR_TITLE_STATE'
DEFAULT_STATE = '~/.local/state/ai-dotfiles/herdr-title'
KEEP_SECONDS = 7 * 24 * 3600
SESSIONS = agent_hooks.Store(ENV, DEFAULT_STATE, KEEP_SECONDS)
PANES = agent_hooks.Store(ENV, DEFAULT_STATE, KEEP_SECONDS, sub='panes')  # the session each pane belongs to
SWARM = 'claude-swarm-'  # the tmux server Claude Code starts for an agent team's teammates
# What a session's labels say under Herdr's done and idle states, by the session's mode: normal
# (a typed prompt; a stop judged done), open (a Codex prompt, until its stop hook answers), pending
# (a stop being judged), ask, wait (its own background work runs on), fail, unknown (no verdict).
AFTER = {'normal': ('done', 'idle'), 'open': ('wait', 'wait'), 'pending': ('run', 'run'), 'ask': ('ask', 'ask'),
         'wait': ('run', 'run'), 'fail': ('fail', 'fail'), 'unknown': ('wait', 'wait')}
SOURCE = 'user:ai-dotfiles-title'  # who reports, to Herdr; beside Herdr's own integration
HERDR_TIMEOUT = 5.0
QUICK = 1.5  # Codex stops an Interrupt or SessionEnd hook at 3 s: those reports give up sooner
NEED = 'need'  # the pane token on rows that wait for the user: ask, fail, or a verdict that never came
NEEDING = ('ask', 'fail', 'unknown')  # not open: Codex's bare wait starts while Codex works
# Herdr's agent list with the rows that need the user first, then Herdr's own attention order.
VIEW = {'source': SOURCE, 'label': 'needs you', 'sort': [
    {'field': {'token': NEED}, 'order': 'desc'}, {'field': 'attention', 'order': 'desc'},
    {'field': 'state_change_seq', 'order': 'desc'}]}
SOCKET_TIMEOUT = 0.5  # a Herdr that does not answer at once is left alone
# A skill named in a prompt: /name, $name or /plugin:name, not a piece of a path.
NAMED = re.compile(r'(?<![\w/.:~-])[/$]((?:[a-z][a-z0-9-]*:)?[a-z][a-z0-9-]*)(?![\w/-]|\.\w)')
NUMBERED = re.compile(r'\s+#?\d+$')  # the PR number after a command word
CUT = re.compile(r'…\s*\[\+\d+ chars\]')  # where Claude Code cuts a scheduled prompt in a Stop's input
KEEP = 'keep'  # the model's word for "this prompt changes nothing"
# What the model reads: the end of the agent's last message, where its question is; a long
# prompt's start and end, since a pasted log sits between the request and the question about it.
REPLY_END = 800
PROMPT_START, PROMPT_END = 500, 300


def config():
    return json.loads(CONFIG.read_text())


def pane():
    """This pane's id when the CLI runs in Herdr, else None."""
    return os.environ.get('HERDR_PANE_ID') if os.environ.get('HERDR_ENV') == '1' else None


def outsider(adapter):
    """Whether the call comes from a session that only shares the pane's environment: a teammate in
    the tmux server Claude Code runs for an agent team, or a headless `claude -p` started from the
    pane (Claude Code marks its hooks sdk-cli)."""
    if SWARM in os.environ.get('TMUX', ''):
        return True
    return adapter.is_headless(os.environ)


@contextlib.contextmanager
def locked():
    """One writer at a time: the hook and its detached model turns change the same state files."""
    SESSIONS.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(SESSIONS.folder / '.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def owner(where):
    """The session the pane belongs to: the last one the user typed a prompt into there."""
    return PANES.load(where).get('session') if where else None


def certain(prompt, settings):
    """The type a prompt names outright, or None: the prompt is a command word (with a PR number
    or not: "approve", "Approve #57."), or the first skill in it that has a type."""
    said = NUMBERED.sub('', prompt.strip().rstrip('.!').lower())
    if said in settings['commands']:
        return settings['commands'][said]
    skills = {**settings['outside'], **settings['skills']}
    for name in NAMED.findall(prompt):
        kind = skills.get(name) or skills.get(name.split(':')[-1])
        if kind:
            return kind
    return None


def labels(state, settings):
    """Herdr's label for each state it detects: working, blocked (a dialog), done (finished and
    not seen yet), idle (seen) and unknown, as type › status › result. Without a type yet, the
    type layer is left out: `run`, `wait › ask`."""
    words = settings['words']
    sep = words['separator']
    head = f"{state['type']}{sep}" if state.get('type') else ''

    def form(word):  # run, wait or idle, or a result under wait
        if word == 'idle':
            return words['idle']
        if word in ('run', 'wait'):
            return head + words[word]
        return f"{head}{words['wait']}{sep}{words[word]}"

    mode = state.get('mode', 'normal')
    done, idle = AFTER.get(mode, AFTER['normal'])
    # An open ask stays while the agent's background work keeps Herdr's working state on.
    return {'working': form('ask' if mode == 'ask' else 'run'), 'blocked': form(state.get('blocked') or 'wait'),
            'done': form(done), 'idle': form(idle), 'unknown': form(idle)}


def herdr(*args, timeout=HERDR_TIMEOUT):
    """Run one herdr command; a Herdr that is missing, slow or unhappy changes nothing."""
    binary = os.environ.get('HERDR_BIN_PATH') or shutil.which('herdr')
    if not binary:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([binary, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=timeout, check=False)


def report(session, settings, timeout=HERDR_TIMEOUT):
    """Label the session's pane with its state as it is now. Herdr keeps only the report with the
    highest seq, and replaces every label with each: the seq is taken before the state is read, and
    every writer saves before it reports, so the report kept carries the latest state. A session
    that has ended or no longer owns its pane reports nothing. The labels name the agent: Herdr
    drops them when it exits, and hides them while another agent runs in the pane."""
    seq = time.time_ns()
    state = SESSIONS.load(session)
    where = state.get('pane')
    if state.get('ended') or not where or owner(where) != session:
        return
    pairs = [arg for status, text in labels(state, settings).items() for arg in ('--state-label', f'{status}={text}')]
    need = ('--token', f'{NEED}=1') if state.get('mode') in NEEDING else ('--clear-token', NEED)
    herdr('pane', 'report-metadata', where, '--source', SOURCE, '--agent', state.get('cli', ''), *pairs, *need,
          '--seq', str(seq), timeout=timeout)


def set_view():
    """Sort Herdr's agent list with the rows that need the user first (VIEW), through Herdr's socket:
    Herdr 0.9.5 has no command for it. The view lasts until Herdr's server exits, so the hook sets
    it again at each typed prompt, stop and resume; a socket that is missing or slow changes nothing."""
    path = os.environ.get('HERDR_SOCKET_PATH')
    if not path:
        return
    request = {'id': 'herdr-title-view', 'method': 'agent.view.set', 'params': VIEW}
    with contextlib.suppress(OSError, ValueError):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(SOCKET_TIMEOUT)
            conn.connect(path)
            conn.sendall((json.dumps(request) + '\n').encode())
            conn.recv(4096)  # Herdr's answer; nothing in it changes what the hook does


def typed(event, settings, crons=()):
    """Whether the user wrote this prompt: not empty, and not a report from a subagent, another
    session or the harness, nor one of the session's scheduled prompts firing (`crons`), which
    arrive as prompts too and say nothing about the user's purpose (Pi says so itself: an
    extension's prompt)."""
    prompt = event.prompt
    return (bool(prompt.strip()) and not prompt.lstrip().startswith(tuple(settings['machine']))
            and event.source != 'extension' and not scheduled(prompt, crons))


def scheduled(prompt, crons):
    """Whether a prompt is one of the session's scheduled prompts (a /loop tick, a cron, a wake-up),
    as the last stop listed them: the prompt itself, or its first 1000 characters when Claude Code
    cut it there. A typed prompt that says exactly the same counts as one too."""
    said = prompt.strip()
    for cron in crons:
        cut = CUT.search(cron)
        start = cron[:cut.start()].strip() if cut else ''
        if said == cron.strip() or (start and said.startswith(start)):
            return True
    return False


def ask_later(request):
    """Hand the prompt to `classify` in a process of its own and return: the model takes
    seconds, and the user's prompt must not wait for it."""
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'classify'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    with contextlib.suppress(OSError):
        child.stdin.write(json.dumps(request).encode())
        child.stdin.close()


def on_prompt(event):
    """A typed prompt makes the session the pane's own and starts a turn in normal mode, reported at
    once with the current type; a prompt the user did not type only counts in the pane's own session.
    Every turn boundary bumps `event`, so a model's late answer can tell it is stale."""
    settings, where = config(), pane()
    if event.subagent:  # a subagent or in-process teammate shares the pane; its prompts are not the user's
        return
    if not typed(event, settings, SESSIONS.load(event.session).get('crons', ())):
        with locked():
            state = SESSIONS.load(event.session)
            if not state or owner(where) != event.session:
                return
            # An open ask waits for the user (and Codex's open mode for its stop hook); anything else,
            # a failure too, gives way to the turn this prompt starts, whose end says what comes next.
            if state.get('mode') not in ('ask', 'open'):
                state['mode'] = 'normal'
            state.update(event=state.get('event', 0) + 1, typed_turn=False, blocked=None)
            SESSIONS.save(event.session, state)
        report(event.session, settings)
        return
    kind = certain(event.prompt, settings)
    with locked():
        state = SESSIONS.load(event.session)
        number = state.get('event', 0) + 1
        mode = 'open' if event.adapter.prompt_starts_open else 'normal'
        state.update(event=number, typed=number, typed_turn=True, mode=mode,
                     blocked=None, ended=False, cli=event.cli, pane=where)
        if kind:
            state['type'] = kind
        SESSIONS.save(event.session, state)
        PANES.save(where, {'session': event.session, 'cli': event.cli})
    report(event.session, settings)
    set_view()
    if not kind:
        ask_later({'job': 'type', 'cli': event.cli, 'session': event.session, 'prompt': event.prompt,
                   'transcript': event.transcript, 'trigger': number})


def model(settings, system, question):
    """A small model's answer, or '' when there is none: a headless `claude -p` that loads no user
    settings (so no hooks, plugins or MCP servers), saves no session, has no tools and cannot see
    the pane."""
    claude = shutil.which('claude')
    if not claude:
        return ''
    chosen = settings['model']
    folder = SESSIONS.folder / 'model'  # a folder without project settings of its own
    folder.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([claude, '-p', question, '--model', chosen['name'], '--tools', '',
                          '--no-session-persistence', '--setting-sources', 'project', '--strict-mcp-config',
                          '--system-prompt', system],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=chosen['timeout'], cwd=folder,
                         env={key: value for key, value in os.environ.items() if not key.startswith('HERDR_')})
    return run.stdout if run.returncode == 0 else ''


def ask(settings, current, said, prompt):
    """The type a small model gives the prompt, or None when it names none. It gets the session's
    current type, the end of the agent's last message and the prompt."""
    listed = '\n'.join(f'{kind}: {means}' for kind, means in settings['types'].items())
    question = (f"Current label: {current or 'none'}\n\nThe agent's last message ended:\n{said or '(none)'}\n\n"
                f"The user's new prompt:\n{prompt}")
    word = pick(model(settings, '\n'.join(settings['model']['type']).replace('{types}', listed), question),
                {*settings['types'], KEEP})
    return None if word == KEEP else word


def pick(said, allowed):
    """The word a model's answer gives, lower case, or None. A word in capitals counts first ("The
    label is DEBUG."), then the answer's first word: the allowed words are everyday words too, so
    one inside a sentence ("I would plan...") is not the answer."""
    found = re.findall(r'[A-Za-z]+', said)
    shouted = [word.lower() for word in found if word.isupper() and word.lower() in allowed]
    if shouted:
        return shouted[0]
    first = found[0].lower() if found else ''
    return first if first in allowed else None


def classify(request):
    """The model's turn for one prompt (job type) or one stop (job stop)."""
    (judge if request.get('job') == 'stop' else classify_type)(request)


def classify_type(request):
    """Ask for the prompt's type, then relabel the pane with it, unless a newer prompt came while
    the model thought. The mode stays as the session has it by then."""
    import agent_sessions  # the CLIs' transcripts; not needed by the hook itself
    settings, session = config(), request['session']
    said = agent_sessions.last_reply(request['cli'], request['transcript']) if request.get('transcript') else ''
    prompt = request['prompt']
    if len(prompt) > PROMPT_START + PROMPT_END:
        prompt = f'{prompt[:PROMPT_START]}\n[...]\n{prompt[-PROMPT_END:]}'
    kind = ask(settings, SESSIONS.load(session).get('type'), said[-REPLY_END:], prompt)
    if not kind:
        return
    with locked():
        state = SESSIONS.load(session)
        if state.get('typed') != request['trigger'] or state.get('ended'):
            return
        state['type'] = kind
        SESSIONS.save(session, state)
    report(session, settings)


def judge(request):
    """Ask what a stopped agent waits for, then set the session's mode by it, unless anything newer
    happened in the session meanwhile. ASK is ask; WAIT is wait only while Claude Code listed work
    of a `background` type or a scheduled prompt, else done (a background command may be a server
    that never ends); DONE is done; no answer is wait with no result, since an ask the model failed
    to see costs the user more than a look."""
    settings, session = config(), request['session']
    word = pick(model(settings, '\n'.join(settings['model']['stop']),
                      f"The agent's last message ended:\n{request['text']}"), {'ask', 'wait', 'done'})
    mode = {'ask': 'ask', 'wait': 'wait' if request.get('background') else 'normal', 'done': 'normal'}.get(word, 'unknown')
    with locked():
        state = SESSIONS.load(session)
        if state.get('event') != request['trigger'] or state.get('ended'):
            return
        state['mode'] = mode
        SESSIONS.save(session, state)
    report(session, settings)


def asks(text, settings):
    """Whether a reply ends by asking, without a model: its last line ends with a question mark
    (quotes, brackets and markup after it aside), or the reply ends with a plan block (Codex)."""
    rules = settings['ask_at_once']
    body = text.rstrip()
    if body.endswith(tuple(rules['endings'])):
        return True
    lines = [line for line in body.splitlines() if line.strip()]
    return bool(lines) and lines[-1].rstrip(' \t"\'*_`)]').endswith(tuple(rules['marks']))


def at_once(event, text, settings):
    """The mode a stop gets without a model, or None: Pi's error or abort, Claude Code's usage-limit
    note since the prompt, or a reply that ends by asking."""
    import agent_sessions  # the CLIs' transcripts
    if event.outcome == 'error':
        return 'fail'
    if event.outcome == 'aborted':
        return 'normal'
    if event.transcript and agent_sessions.note_since_prompt(event.cli, event.transcript, settings['usage_limit_note']):
        return 'fail'
    return 'ask' if asks(text, settings) else None


def on_stop(event):
    """A turn ended. The label says ask, fail or the like at once when it can; otherwise it keeps
    run while a small model judges the reply (about 3 s). A turn the user did not start leaves an
    open ask open: only an error replaces it."""
    import agent_sessions  # the CLIs' transcripts
    settings = config()
    if event.subagent:
        return
    text = event.last_message or (agent_sessions.last_reply(event.cli, event.transcript) if event.transcript else '')
    with locked():
        state = SESSIONS.load(event.session)
        if not state or owner(pane()) != event.session:
            return
        number = state.get('event', 0) + 1
        mode = at_once(event, text, settings)
        if mode != 'fail' and state.get('mode') == 'ask' and not state.get('typed_turn'):
            mode = 'ask'
        # The scheduled prompts as of this stop: the next prompt that is one of them is not typed.
        state.update(event=number, mode=mode or 'pending', blocked=None, crons=list(event.crons))
        SESSIONS.save(event.session, state)
    report(event.session, settings)
    set_view()
    if mode is None:
        background = any(task in settings['background'] for task in event.tasks) or bool(event.crons)
        ask_later({'job': 'stop', 'cli': event.cli, 'session': event.session, 'trigger': number,
                   'text': text[-REPLY_END:], 'background': background})


def settle(event, mode):
    """End the turn in `mode` at once: an API error (fail), Codex's interrupt (normal)."""
    if event.subagent:
        return
    with locked():
        state = SESSIONS.load(event.session)
        if not state or owner(pane()) != event.session:
            return
        state.update(event=state.get('event', 0) + 1, mode=mode, blocked=None)
        SESSIONS.save(event.session, state)
    report(event.session, config(), timeout=QUICK)


def on_dialog(event, word):
    """A dialog is about to open: the blocked label says what it waits for, ask or allow, until the
    next prompt or turn end. A subagent's dialog opens in the lead's pane, so it counts too."""
    with locked():
        state = SESSIONS.load(event.session)
        if not state or owner(pane()) != event.session:
            return
        state['blocked'] = word
        SESSIONS.save(event.session, state)
    report(event.session, config())


def on_start(event):
    """A session resumed (Claude Code's --resume, --continue and /resume; Pi on a kept session, at
    launch or by /resume, Herdr's restore included): its kept state labels the pane again, unless
    the pane belongs to another session. Codex has no such hook: its pane waits for a typed prompt."""
    if event.subagent or event.source != 'resume':
        return
    where = pane()
    with locked():
        state, mine = SESSIONS.load(event.session), owner(where)
        if not state or (mine and mine != event.session):
            return
        if state.get('mode') == 'pending':  # its verdict died with the old process
            state['mode'] = 'unknown'
        state.update(event=state.get('event', 0) + 1, ended=False, pane=where, cli=event.cli, blocked=None)
        SESSIONS.save(event.session, state)
        PANES.save(where, {'session': event.session, 'cli': event.cli})
    report(event.session, config())
    set_view()


def cmd_classify(_args):
    with contextlib.suppress(Exception):  # nobody is listening: a failure leaves the labels as they are
        classify(json.loads(sys.stdin.read()))
    return 0


def clear(where, cli, seq):
    """Take the labels and the need token off the pane: Herdr keeps a token until it is cleared."""
    herdr('pane', 'report-metadata', where, '--source', SOURCE, '--agent', cli, '--clear-state-labels',
          '--clear-token', NEED, '--seq', str(seq), timeout=QUICK)


def on_end(event):
    """The session is over: its labels come off the pane. Its state stays (pruned after a week), so a
    resumed session finds its type. A subagent's end is not the pane's, Pi's reload keeps the
    session, and a session the pane no longer belongs to (Codex ends an old chat late) changes nothing."""
    if event.subagent or event.adapter.session_survives_end(event.reason):
        return
    where = pane()
    with locked():
        mine = owner(where)
        if mine and mine != event.session:
            return
        seq = time.time_ns()  # under the lock: a session that claims the pane after this reports above it
        state = SESSIONS.load(event.session)
        if state:
            if state.get('mode') == 'pending':
                state['mode'] = 'unknown'
            state.update(event=state.get('event', 0) + 1, ended=True)
            SESSIONS.save(event.session, state)
        PANES.file(where).unlink(missing_ok=True)
    clear(where, event.cli, seq)


HANDLERS = {'prompt': on_prompt, 'stop': on_stop, 'error': lambda event: settle(event, 'fail'),
            'interrupt': lambda event: settle(event, 'normal'),
            'permission': lambda event: on_dialog(event, 'ask' if event.action == 'ask' else 'allow'),
            'pre': lambda event: on_dialog(event, 'ask'),  # Claude Code's question and plan tools only
            'form': lambda event: on_dialog(event, 'ask'),  # an MCP server asks for input
            'start': on_start, 'end': on_end}


def hook(event):
    """The door's call (lib/door.py) for one event; the reply is always none, so each CLI gets its
    quiet reply. Nothing runs outside a Herdr pane, for a session that only shares the pane's
    environment, or without a session id."""
    if pane() and not outsider(event.adapter) and event.session:
        if event.kind == 'prompt':
            SESSIONS.prune(time.time())
            PANES.prune(time.time())
        HANDLERS[event.kind](event)
    return None


def parser():
    top = argparse.ArgumentParser(prog='herdr-title', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    sub.add_parser('classify', help="the model's turn: a request as JSON on stdin (the hook starts it)"
                   ).set_defaults(run=cmd_classify)
    return top


def main(argv=None):
    try:
        args = parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    except SystemExit as error:
        return int(error.code or 0)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
