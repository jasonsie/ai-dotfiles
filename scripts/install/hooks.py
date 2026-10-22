#!/usr/bin/env python3
"""Install the `learn` skill's hooks into each CLI; writes unless --dry-run.

Each CLI gets two hooks that run skills/learn/hooks/learn_hook.py: one on every user
prompt and one at the end of every turn. The hooks are merged into the CLI's own hook file
as one entry per event; every other hook stays as it is:
  Claude Code   ~/.claude/settings.json  "hooks": UserPromptSubmit, Stop
  Codex         ~/.codex/hooks.json      UserPromptSubmit, Stop (approve once in /hooks)
  Antigravity   ~/.gemini/config/hooks.json  named entries for PreInvocation, Stop
Pi has no hooks: skills.py links skills/learn/hooks/pi-learn.ts as its extension.

An entry counts as this script's when its command runs learn_hook.py; anything else in
its place is refused. Files are never written through a symlink, are backed up before
writing, and are restored on failure. --uninstall removes only these entries, leaving
every other hook as it is.
"""
import copy
import json
from pathlib import Path
import shlex
import sys

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
HOOK = WORKSPACE / 'skills/learn/hooks/learn_hook.py'
MARK = 'skills/learn/hooks/learn_hook.py'
EVENTS = {
    'claude': {'UserPromptSubmit': 'prompt', 'Stop': 'stop'},
    'codex': {'UserPromptSubmit': 'prompt', 'Stop': 'stop'},
    'agy': {'PreInvocation': 'prompt', 'Stop': 'stop'},
}
AGY_NAMES = {'prompt': 'ai-dotfiles-learn-prompt', 'stop': 'ai-dotfiles-learn-stop'}
TIMEOUT = 10


def handler(cli, mode, hook=HOOK):
    # `|| true`: a missing script or bad arguments exit 2, which would block every prompt in
    # Claude Code and turn the error into a prompt at Codex's Stop. All three run it in a shell.
    command = shlex.join(['python3', str(hook), mode, '--cli', cli]) + ' || true'
    return {'type': 'command', 'command': command, 'timeout': TIMEOUT}


def is_ours(entry):
    return isinstance(entry, dict) and MARK in str(entry.get('command', ''))


def merge_events(data, cli, hook):
    """Claude Code and Codex: event -> [{hooks: [handler]}]; ours is replaced in place or appended."""
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    for event, mode in EVENTS[cli].items():
        groups = hooks.get(event) or []
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        wanted = {'hooks': [handler(cli, mode, hook)]}
        mine = [i for i, group in enumerate(groups)
                if isinstance(group, dict) and any(is_ours(h) for h in group.get('hooks') or [])]
        hooks[event] = groups[:mine[0]] + [wanted] + groups[mine[0] + 1:] if mine else groups + [wanted]


def check_agy_entry(data, name):
    current = data.get(name)
    if current is not None:
        handlers = [h for value in current.values() if isinstance(value, list) for h in value] \
            if isinstance(current, dict) else []
        if not handlers or not all(is_ours(h) for h in handlers):
            raise ValueError(f'Not created by this script; refusing to replace hook entry {name!r}')


def merge_agy(data, hook):
    """Antigravity: named top-level entries, each holding its handlers directly under the event."""
    for event, mode in EVENTS['agy'].items():
        name = AGY_NAMES[mode]
        check_agy_entry(data, name)
        data[name] = {event: [handler('agy', mode, hook)]}


def remove_events(data, cli):
    """Claude Code and Codex: drop our handlers; emptied groups, events, and "hooks" go too."""
    hooks = data.get('hooks')
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    changed = False
    for event in EVENTS[cli]:
        groups = hooks.get(event)
        if groups is None:
            continue
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        kept = []
        for group in groups:
            inner = group.get('hooks') if isinstance(group, dict) else None
            if isinstance(inner, list) and any(is_ours(h) for h in inner):
                inner = [h for h in inner if not is_ours(h)]
                if inner:
                    kept.append({**group, 'hooks': inner})
            else:
                kept.append(group)
        if kept == groups:
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if changed and not hooks:
        del data['hooks']


def remove_agy(data):
    for name in AGY_NAMES.values():
        check_agy_entry(data, name)
        data.pop(name, None)


def plan_file(home, cli, hook=HOOK, uninstall=False):
    """(path, before, after) for one CLI's hook file, or None when nothing changes."""
    path = installer.path(home, cli, 'hooks')
    if path is None:
        return None  # no hook file: Pi takes an extension, linked by skills.py
    if cli not in EVENTS:
        raise ValueError(f'No hook format for {cli} yet; add it to scripts/install/hooks.py')
    if not path.parent.is_dir():
        return None  # CLI not set up on this machine

    def change(old):
        original = json.loads(old) if old.strip() else {}
        if not isinstance(original, dict):
            raise ValueError(f'{path}: expected a JSON object')
        data = copy.deepcopy(original)
        if cli == 'agy' and uninstall:
            remove_agy(data)
        elif cli == 'agy':
            merge_agy(data, hook)
        elif uninstall:
            remove_events(data, cli)
        else:
            merge_events(data, cli, hook)
        return old if data == original else (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()

    return installer.edit(path, change)


def install(home, add, remove=(), apply=False, hook=HOOK):
    """Merge our hooks into the hook files of the CLIs in `add`; take them out for `remove`."""
    plans = [plan_file(home, cli, hook) for cli in add] + [plan_file(home, cli, hook, True) for cli in remove]
    changes = [change for change in plans if change]
    installer.show(changes, apply)
    if apply and changes:
        print(f'Backup: {installer.apply(home, changes, backup="settings")}')
        if 'codex' in add and any(path == installer.path(home, 'codex', 'hooks') for path, _, _ in changes):
            print('Codex: approve the new hooks once with /hooks; Codex runs no unreviewed hook.')
    return len(changes)


def run(home, target, write, uninstall, hook=HOOK):
    """Hooks for the CLIs switched on; none for those switched off, or for any on --uninstall."""
    selected = installer.scope(target)
    on, off = ((), selected) if uninstall else installer.split(selected)
    return install(home, on, off, write, hook)


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('hooks', lambda: run(args.home, args.target, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
