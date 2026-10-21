#!/usr/bin/env python3
"""Install the `learn` skill's hooks into each CLI; writes unless --dry-run.

Each CLI gets two hooks that run skills/learn/hooks/learn_hook.py: one on every user
prompt and one at the end of every turn. The hooks are merged into the CLI's own hook file
as one entry per event; every other hook stays as it is:
  Claude Code   ~/.claude/settings.json  "hooks": UserPromptSubmit, Stop
  Codex         ~/.codex/hooks.json      UserPromptSubmit, Stop (approve once in /hooks)
  Antigravity   ~/.gemini/config/hooks.json  named entries for PreInvocation, Stop
Pi has no hooks; skills/learn/hooks/pi-learn.ts is linked into its extensions folder.

An entry counts as this script's when its command runs learn_hook.py (or, for Pi, when
the link points at pi-learn.ts); anything else in its place is refused. Files are never
written through a symlink, are backed up before writing, and are restored on failure.
--uninstall removes only these entries and the Pi link, leaving every other hook as it is.
"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
HOOK = WORKSPACE / 'skills/learn/hooks/learn_hook.py'
PI_SOURCE = WORKSPACE / 'skills/learn/hooks/pi-learn.ts'
MARK = 'skills/learn/hooks/learn_hook.py'
PI_MARK = 'skills/learn/hooks/pi-learn.ts'
FILES = {
    'claude': '.claude/settings.json',
    'codex': '.codex/hooks.json',
    'agy': '.gemini/config/hooks.json',
}
EVENTS = {
    'claude': {'UserPromptSubmit': 'prompt', 'Stop': 'stop'},
    'codex': {'UserPromptSubmit': 'prompt', 'Stop': 'stop'},
    'agy': {'PreInvocation': 'prompt', 'Stop': 'stop'},
}
AGY_NAMES = {'prompt': 'ai-dotfiles-learn-prompt', 'stop': 'ai-dotfiles-learn-stop'}
PI_LINK = 'extensions/ai-dotfiles-learn.ts'
TARGETS = ('claude', 'codex', 'agy', 'pi')
TIMEOUT = 10

# Backup, atomic write, and rollback come from the settings installer.
_spec = importlib.util.spec_from_file_location('apply_settings', WORKSPACE / 'scripts/apply-settings.py')
settings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(settings)


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
    path = home / FILES[cli]
    if not path.parent.is_dir():
        return None  # CLI not set up on this machine
    if path.is_symlink():
        raise ValueError(f'Refusing to write through symlinked file: {path}')
    before = path.read_bytes() if path.exists() else b''
    original = json.loads(before) if before.strip() else {}
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
    if data == original:
        return None
    return path, before, (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()


def pi_dir(home):
    return settings.settings_path(home, 'pi').parent


def plan_pi(home, source=PI_SOURCE, uninstall=False):
    """(link path, current target or None, wanted target or None), or None when nothing changes."""
    folder = pi_dir(home)
    if not folder.is_dir():
        return None
    path = folder / PI_LINK
    current = os.readlink(path) if path.is_symlink() else None
    if uninstall:
        if not (path.exists() or path.is_symlink()):
            return None
        if not (current and current.endswith(PI_MARK)):
            raise ValueError(f'Not created by this script; refusing to remove: {path}')
        return path, current, None
    if current == str(source):
        return None
    if (path.exists() or path.is_symlink()) and not (current and current.endswith(PI_MARK)):
        raise ValueError(f'Not created by this script; refusing to replace: {path}')
    return path, current, str(source)


def set_link(path, target):
    if target is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        link = Path(temp) / 'link'
        link.symlink_to(target)
        os.replace(link, path)


def run(home, changes, link):
    """Write everything or nothing; returns the backup folder of the file changes."""
    if link:
        set_link(link[0], link[2])
    try:
        return settings.apply(home, changes) if changes else None
    except BaseException:
        if link:
            set_link(link[0], link[1])
        raise


def install(home, targets, apply=False, hook=HOOK, pi_source=PI_SOURCE, uninstall=False):
    changes = [c for c in (plan_file(home, cli, hook, uninstall) for cli in targets if cli in FILES) if c]
    link = plan_pi(home, pi_source, uninstall) if 'pi' in targets else None
    for path, _, _ in changes:
        print(f'{"Update" if apply else "Would update"}: {path}')
    if link and uninstall:
        print(f'{"Remove" if apply else "Would remove"}: {link[0]}')
    elif link:
        print(f'{"Link" if apply else "Would link"}: {link[0]} -> {link[2]}')
    if apply and (changes or link):
        backup = run(home, changes, link)
        if backup:
            print(f'Backup: {backup}')
        if not uninstall and any(path == home / FILES['codex'] for path, _, _ in changes):
            print('Codex: approve the new hooks once with /hooks; Codex runs no unreviewed hook.')
    return len(changes) + bool(link)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--target', choices=('all', *TARGETS), default='all')
    parser.add_argument('--dry-run', action='store_true', help='preview only; write nothing')
    parser.add_argument('--uninstall', action='store_true', help='remove these hooks and the Pi link')
    args = parser.parse_args()
    write = not args.dry_run
    targets = TARGETS if args.target == 'all' else (args.target,)
    try:
        count = install(args.home.expanduser().resolve(), targets, write, uninstall=args.uninstall)
    except (OSError, ValueError) as e:
        print(f'hooks: {e}', file=sys.stderr)
        return 1
    print(f'hooks: {count} changes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
