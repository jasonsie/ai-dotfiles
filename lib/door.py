"""door: `ai-dotfiles hook <kind> --cli <cli>`, the one hook call that serves every feature.

Every CLI reaches the features through this door. The hook files of Claude Code, Codex and
Antigravity hold one entry per event that runs it (lib/install/hooks.py writes them), Pi's
extension (scripts/agent_hooks.ts) sends it each event, and a cloud session's project hooks
(.claude/settings.json) call it too. It reads the CLI's hook input once, then runs, in this one
process and in the features' order (lib/features.py), every feature whose feature.json wants the
event (for a tool event: the tool's action), calling its module's hook(event):

- each sees the tool input as the feature before it left it: a Rewrite steers the ones after it;
- the first Deny ends the chain, and carries the notes said before it;
- the notes of every feature are joined, one per line, and so are the lines for the person (Shown);
- a feature that raises or runs past its budget is skipped; before a tool call its failed(error) is
  said in its place, when it has one. A failure never blocks a tool call.

These are the semantics Pi's extension had when it played each feature in turn. One entry per event,
whose command names no file in the repo, is what lets a feature change or move without a new hook
entry: Codex trusts each entry by its hash and asks for an approval whenever one changes. The reply
is rendered in the CLI's own shape (scripts/agent_hooks.py). In a cloud session only the features
whose declaration says cloud run.

Time: each CLI gives a call so long (agent_hooks.TIMEOUTS, which the installer writes into the entry;
Codex allows SessionEnd and Interrupt 3 s at most), and the door answers within it. A feature gets its
budget or what is left of the call's time less MARGIN (for starting, answering and exiting), whichever
is less. An alarm (SIGALRM) keeps it: Overrun is raised inside the feature, so a blocking wait (a git
command, a lock, a socket) is cut short too, and subprocess.run kills its child on the way out.
Overrun is a BaseException, so a feature's own `except Exception` does not swallow it.

Claude Code's worktree events (agent_hooks.RAW) are answered as Claude reads them: WorktreeCreate's
reply is the new worktree's path on stdout, no JSON. A feature that fails one says why on stderr,
after its name, and the door exits 1: there is no worktree to enter. Any other bad call stays silent
and exits 0, since status 2 and stderr would steer the CLI.

The `ai-dotfiles` command starts this file with the Python the hooks step linked (see there).
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import signal
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as declared  # noqa: E402  (feature.json, found by folder; it puts scripts/ on the path)
import agent_hooks  # noqa: E402  (the CLIs' hook formats)
from agent_hooks import Continue, Deny, Note, Rewrite, Shown  # noqa: E402

MARGIN = 0.5  # seconds of a call's time kept for starting, answering and exiting
LOADED = {}  # feature module path -> module: each is imported once per process


class Overrun(BaseException):
    """A feature ran past its time."""


@contextlib.contextmanager
def limit(seconds):
    """Raise Overrun in the code inside once `seconds` have passed. Signals reach only the main
    thread, so anywhere else the code runs unlimited."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def ring(_signum, _frame):
        raise Overrun(f'took more than {seconds:.2g} s')

    before = signal.signal(signal.SIGALRM, ring)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, before)


def module_of(feature):
    """The feature's module, imported once per process under a name of its own: two features may
    give their files one name."""
    path = str(feature.module)
    if path not in LOADED:
        name = 'feature_' + re.sub(r'\W', '_', feature.name) + '_' + hashlib.sha1(path.encode()).hexdigest()[:8]
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, path
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses look their module up there
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
        LOADED[path] = module
    return LOADED[path]


def run(feature, event, seconds):
    """(reply, None), or (None, the error) when the feature failed, could not load, or ran out of time."""
    if seconds <= 0:
        return None, Overrun('had no time left')
    try:
        with limit(seconds):
            return module_of(feature).hook(event), None
    except (Exception, Overrun, SystemExit) as error:
        return None, error


def failure(feature, kind, error):
    """What is said in a failed feature's place: before a tool call, its failed(error); else nothing."""
    module = LOADED.get(str(feature.module))
    if kind != 'pre' or module is None or not hasattr(module, 'failed'):
        return None
    try:
        return module.failed(error)
    except Exception:
        return None


def chain(kind, event, chosen, deadline, clock):
    """The chosen features' one reply to an event (the rules are in this module's docstring)."""
    notes, shown = [], []
    tool_input, rewritten, verdict = event.tool_input, False, None
    for feature in chosen:
        reply, error = run(feature, replace(event, tool_input=tool_input),
                           min(feature.budget[kind], deadline - clock()))
        if error is not None:
            reply = failure(feature, kind, error)
        if isinstance(reply, Shown):
            shown.append(reply)
            reply = reply.reply
        if isinstance(reply, (Deny, Continue)):
            verdict = reply
            break
        if isinstance(reply, Rewrite):
            tool_input, rewritten = reply.tool_input, True
            reply = Note(reply.note)
        if isinstance(reply, Note) and reply.text:
            notes.append(reply.text)
    said = '\n'.join(notes)
    if isinstance(verdict, Deny):
        verdict = Deny(verdict.reason, '\n'.join(part for part in (said, verdict.note) if part))
    elif verdict is None:
        verdict = Rewrite(tool_input, said) if rewritten else Note(said) if said else None
    if shown:
        verdict = Shown(verdict, '\n'.join(each.text for each in shown if each.text), shown[-1].status)
    return verdict


def answer_raw(kind, event, chosen, deadline, clock):
    """(the first reply, the failures as lines) for a worktree event: the first feature that
    answers ends it."""
    failures = []
    for feature in chosen:
        reply, error = run(feature, event, min(feature.budget[kind], deadline - clock()))
        if error is not None:
            failures.append(f'{feature.name}: {error}')
        elif reply is not None:
            return reply, failures
    return None, failures


def call(cli, kind, data, chosen, stderr=None, clock=time.monotonic):
    """(output, exit status) of one hook call from `cli`: the chosen features that want it run, and
    their reply is rendered for the CLI (a dict for JSON, text for a RAW kind, None for nothing)."""
    deadline = clock() + agent_hooks.timeout(cli, kind) - MARGIN
    event = agent_hooks.read(cli, kind, data)
    wanting = [feature for feature in chosen if feature.wanted(cli, kind, event.action)]
    if kind not in agent_hooks.RAW:
        return agent_hooks.render(cli, kind, chain(kind, event, wanting, deadline, clock)), 0
    reply, failures = answer_raw(kind, event, wanting, deadline, clock)
    for line in failures:
        print(line, file=stderr or sys.stderr)
    return agent_hooks.render(cli, kind, reply), 1 if failures and reply is None else 0


def parser():
    top = argparse.ArgumentParser(prog='ai-dotfiles', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    hook = sub.add_parser('hook', help="one CLI hook call: the CLI's JSON on stdin, its reply on stdout")
    hook.add_argument('kind', choices=tuple(agent_hooks.NATIVE))
    hook.add_argument('--cli', choices=agent_hooks.CLIS, required=True)
    return top


def main(argv=None, root=declared.ROOT, stdin=None, stdout=None, stderr=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser().parse_args(argv)
    except SystemExit:
        return 0
    try:
        data = json.loads(stdin.read() or '{}')
    except ValueError:
        data = {}
    try:
        cloud = agent_hooks.in_cloud()
        chosen = [feature for feature in declared.find(root) if feature.cloud or not cloud]
        out, status = call(args.cli, args.kind, data, chosen, stderr)
    except Exception as error:  # the door's own failure never blocks the CLI: its quiet reply
        print(f'ai-dotfiles hook: {error}', file=stderr)
        out, status = agent_hooks.render(args.cli, args.kind, None), 0
    if out is not None:
        stdout.write((out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)) + '\n')
    return status


if __name__ == '__main__':
    sys.exit(main())
