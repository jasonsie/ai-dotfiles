#!/usr/bin/env python3
"""Install the `daily-log` skill's hooks into each CLI; writes unless --dry-run.

Each CLI gets two hooks that run skills/daily-log/scripts/daily_log.py: one after every
file edit (PostToolUse, filtered by tool name) and one at the end of every turn (Stop).
They are merged into the CLI's own hook file as one entry per event; every other hook
stays as it is:
  Claude Code   ~/.claude/settings.json      "hooks": PostToolUse (Edit, Write, NotebookEdit), Stop
  Codex         ~/.codex/hooks.json          PostToolUse (Edit, Write), Stop (approve once in /hooks)
  Antigravity   ~/.gemini/config/hooks.json  named entries for PostToolUse (its file tools), Stop
Pi has no hooks: skills.py links skills/daily-log/hooks/daily-log.ts as its extension.

An entry counts as this script's when its command runs daily_log.py; anything else in
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
HOOK = WORKSPACE / 'skills/daily-log/scripts/daily_log.py'
MARK = 'skills/daily-log/scripts/daily_log.py'
EVENTS = {  # per CLI: (event, mode, tool-name matcher or None)
    'claude': (('PostToolUse', 'tool', 'Edit|Write|NotebookEdit'), ('Stop', 'stop', None)),
    'codex': (('PostToolUse', 'tool', 'Edit|Write'), ('Stop', 'stop', None)),
    'agy': (('PostToolUse', 'tool', 'write_to_file|replace_file_content|multi_replace_file_content'),
            ('Stop', 'stop', None)),
}
AGY_NAMES = {'tool': 'ai-dotfiles-daily-log-tool', 'stop': 'ai-dotfiles-daily-log-stop'}
TOOL_EVENTS = ('PreToolUse', 'PostToolUse')  # Antigravity: these take matcher groups, the rest bare handlers
TIMEOUT = 10


def handler(cli, mode, hook=HOOK):
    # `|| true`: a missing script or bad arguments exit 2, which the CLIs act on (the error goes to
    # the model, and at Stop it keeps the turn going). All three run it in a shell.
    command = shlex.join(['python3', str(hook), 'hook', mode, '--cli', cli]) + ' || true'
    return {'type': 'command', 'command': command, 'timeout': TIMEOUT}


def group(handlers, matcher):
    """A matcher group; Stop and the like take no matcher, so the key is left out."""
    return {'matcher': matcher, 'hooks': handlers} if matcher else {'hooks': handlers}


def is_ours(entry):
    return isinstance(entry, dict) and MARK in str(entry.get('command', ''))


def holds_ours(item):
    inner = item.get('hooks') if isinstance(item, dict) else None
    return isinstance(inner, list) and any(is_ours(h) for h in inner)


def strip_ours(groups):
    """(groups without our handlers, where the first group that held one stood, or None).
    A foreign handler that shares a group with ours stays, in a group of its own."""
    kept, at = [], None
    for item in groups:
        if not holds_ours(item):
            kept.append(item)
            continue
        if at is None:
            at = len(kept)
        rest = [h for h in item['hooks'] if not is_ours(h)]
        if rest:
            kept.append({**item, 'hooks': rest})
    return kept, at


def merge_events(data, cli, hook):
    """Claude Code and Codex: event -> [{matcher, hooks: [handler]}]. Our group takes the place of
    the first one that held ours, or is appended; every other group and handler stays."""
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    for event, mode, matcher in EVENTS[cli]:
        groups = hooks.get(event)
        if groups is None:
            groups = []
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        kept, at = strip_ours(groups)
        kept.insert(len(kept) if at is None else at, group([handler(cli, mode, hook)], matcher))
        hooks[event] = kept


def agy_handlers(entry):
    """Every handler in a named entry, under any event, whether in a matcher group or bare."""
    found = []
    for value in entry.values():
        if isinstance(value, list):
            for item in value:
                inner = item.get('hooks') if isinstance(item, dict) else None
                found.extend(inner if isinstance(inner, list) else [item])
    return found


def check_agy_entry(data, name):
    current = data.get(name)
    if current is not None:
        handlers = agy_handlers(current) if isinstance(current, dict) else []
        if not handlers or not all(is_ours(h) for h in handlers):
            raise ValueError(f'Not created by this script; refusing to replace hook entry {name!r}')


def merge_agy(data, hook):
    """Antigravity: named top-level entries, one event each; keys that are not lists (its
    `enabled` switch) are kept."""
    for event, mode, matcher in EVENTS['agy']:
        name = AGY_NAMES[mode]
        check_agy_entry(data, name)
        wanted = handler('agy', mode, hook)
        kept = {key: value for key, value in (data.get(name) or {}).items() if not isinstance(value, list)}
        data[name] = {**kept, event: [group([wanted], matcher)] if event in TOOL_EVENTS else [wanted]}


def remove_events(data, cli):
    """Claude Code and Codex: drop our handlers; emptied groups, events, and "hooks" go too."""
    hooks = data.get('hooks')
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    changed = False
    for event, _, _ in EVENTS[cli]:
        groups = hooks.get(event)
        if groups is None:
            continue
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        kept, _ = strip_ours(groups)
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
