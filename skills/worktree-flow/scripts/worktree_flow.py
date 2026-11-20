#!/usr/bin/env python3
"""worktree-flow: toggle a repo's worktree flow, once the person says yes in a macOS dialog.

  worktree_flow.py [--repo DIR]   ask "Turn the worktree flow on|off in <repo>?"; on OK, flip it

The flow switch is worktree-guard's: the local git config `worktree-guard.flow`, `true` when on,
unset when off (a repo starts off). An agent runs this when the person invokes /worktree-flow;
the dialog is the person's yes, which no agent and no prompt the person did not type can give.
Cancel, no answer, or no dialog at all (no GUI): nothing changes, exit 1 with the reason.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'worktree-guard' / 'scripts'))
import worktree_guard as guard  # noqa: E402  (the flow switch: its key, its reading, the repo's main checkout)

WAIT = 60  # seconds the dialog stays up before it gives up (a no); under Claude Code's 2-minute shell default


def ask(question):
    """True when the person clicks OK; False on Cancel or no answer; None when no dialog opens."""
    script = (f'display dialog {applescript(question)} with title "worktree-flow" '
              f'buttons {{"Cancel", "OK"}} default button "Cancel" cancel button "Cancel" giving up after {WAIT}')
    try:
        run = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=WAIT + 15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode:
        return False if '-128' in run.stderr else None  # -128: the person clicked Cancel
    return 'button returned:OK' in run.stdout and 'gave up:true' not in run.stdout


def applescript(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='worktree_flow.py', description="toggle the repo's worktree flow, after a yes in a dialog")
    parser.add_argument('--repo', help='a folder in the repository (default: here)')
    args = parser.parse_args(argv)
    main_checkout = guard.repo_main(args.repo)
    turn = 'off' if guard.flow_on(main_checkout) else 'on'
    answer = ask(f'Turn the worktree flow {turn} in {main_checkout.name}?')
    if not answer:
        why = 'the person said no' if answer is False else 'no dialog could open (no GUI?)'
        print(f'worktree-flow: unchanged, {why}: flow stays {"on" if turn == "off" else "off"} '
              f'in {main_checkout}', file=sys.stderr)
        return 1
    if turn == 'on':
        guard.git(main_checkout, 'config', '--local', guard.FLOW_KEY, 'true')
    else:
        guard.git(main_checkout, 'config', '--local', '--unset', guard.FLOW_KEY, check=False)
    print(f'worktree-flow: flow: {turn} in {main_checkout}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
