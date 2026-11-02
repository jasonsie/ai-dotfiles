#!/usr/bin/env python3
"""Install the skills' hooks into each CLI: daily-log and worktree-guard; writes unless --dry-run.

daily-log (skills/daily-log/scripts/daily_log.py) runs after every file edit (PostToolUse,
filtered by tool name) and at the end of every turn (Stop). worktree-guard
(skills/worktree-guard/scripts/worktree_guard.py) runs before edits and shell commands
(PreToolUse; Antigravity also before reads) and when a session ends (SessionEnd). Each
feature's hooks are merged into the CLI's own hook file as one entry per event; every other
hook stays as it is:
  Claude Code   ~/.claude/settings.json      "hooks": PostToolUse, Stop; PreToolUse, SessionEnd
  Codex         ~/.codex/hooks.json          the same (approve once in /hooks)
  Antigravity   ~/.gemini/config/hooks.json  named entries per feature and event (no SessionEnd)
Pi has no hooks: skills.py links scripts/agent_hooks.ts as its extension. The native events
and matchers come from scripts/agent_hooks.py.

An entry counts as a feature's when its command runs that feature's script; anything else in
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
sys.path.insert(0, str(WORKSPACE / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats)

HOOK = WORKSPACE / 'skills/daily-log/scripts/daily_log.py'
MARK = 'skills/daily-log/scripts/daily_log.py'
WANTS = (('tool', 'edit'), ('stop', None))  # daily-log: after every edit, and when a turn ends
EVENTS = {cli: agent_hooks.native_events(cli, WANTS) for cli in agent_hooks.HOOK_FILE_CLIS}
AGY_NAMES = {'tool': 'ai-dotfiles-daily-log-tool', 'stop': 'ai-dotfiles-daily-log-stop'}
TOOL_EVENTS = ('PreToolUse', 'PostToolUse')  # Antigravity: these take matcher groups, the rest bare handlers
TIMEOUT = 10
GUARD_MARK = 'skills/worktree-guard/scripts/worktree_guard.py'
GUARD_WANTS = {  # before edits and shell commands, and at session end; Claude Code moves itself, so
    # its reads are left alone; Antigravity has no SessionEnd but has read tools to steer
    'claude': (('pre', ('edit', 'shell')), ('end', None)),
    'codex': (('pre', ('edit', 'shell')), ('end', None)),
    'agy': (('pre', ('edit', 'shell', 'read')),),
}
GUARD_TIMEOUT = 60  # making a linked worktree in a big repository takes a while


class Feature:
    """One skill's hooks: its script, its native events per CLI, its handlers' timeout."""

    def __init__(self, name, script, mark, events, timeout):
        self.name, self.script, self.mark, self.events, self.timeout = name, Path(script), mark, events, timeout
        self.agy_names = {mode: f'ai-dotfiles-{name}-{mode}' for _, mode, _ in events.get('agy', ())}


def daily_log(hook=HOOK):
    return Feature('daily-log', hook, MARK, EVENTS, TIMEOUT)


def worktree_guard(hook=HOOK):
    """The guard, found beside daily-log in the same checkout (`hook` is daily-log's script)."""
    events = {cli: agent_hooks.native_events(cli, wants) for cli, wants in GUARD_WANTS.items()}
    return Feature('worktree-guard', Path(hook).parents[3] / GUARD_MARK, GUARD_MARK, events, GUARD_TIMEOUT)


def features(hook=HOOK):
    return [daily_log(hook), worktree_guard(hook)]


DAILY_LOG = daily_log()


def handler(cli, mode, hook=HOOK, timeout=TIMEOUT):
    # `|| true`: a missing script or bad arguments exit 2, which the CLIs act on (the error goes to
    # the model, and at Stop it keeps the turn going). All three run it in a shell.
    command = shlex.join(['python3', str(hook), 'hook', mode, '--cli', cli]) + ' || true'
    return {'type': 'command', 'command': command, 'timeout': timeout}


def group(handlers, matcher):
    """A matcher group; Stop and the like take no matcher, so the key is left out."""
    return {'matcher': matcher, 'hooks': handlers} if matcher else {'hooks': handlers}


def is_ours(entry, mark=MARK):
    return isinstance(entry, dict) and mark in str(entry.get('command', ''))


def holds_ours(item, mark=MARK):
    inner = item.get('hooks') if isinstance(item, dict) else None
    return isinstance(inner, list) and any(is_ours(h, mark) for h in inner)


def strip_ours(groups, mark=MARK):
    """(groups without our handlers, where the first group that held one stood, or None).
    A foreign handler that shares a group with ours stays, in a group of its own."""
    kept, at = [], None
    for item in groups:
        if not holds_ours(item, mark):
            kept.append(item)
            continue
        if at is None:
            at = len(kept)
        rest = [h for h in item['hooks'] if not is_ours(h, mark)]
        if rest:
            kept.append({**item, 'hooks': rest})
    return kept, at


def merge_events(data, cli, feature=DAILY_LOG):
    """Claude Code and Codex: event -> [{matcher, hooks: [handler]}]. Our group takes the place of
    the first one that held ours, or is appended; every other group and handler stays."""
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    for event, mode, matcher in feature.events[cli]:
        groups = hooks.get(event)
        if groups is None:
            groups = []
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        kept, at = strip_ours(groups, feature.mark)
        wanted = handler(cli, mode, feature.script, feature.timeout)
        kept.insert(len(kept) if at is None else at, group([wanted], matcher))
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


def check_agy_entry(data, name, mark=MARK):
    current = data.get(name)
    if current is not None:
        handlers = agy_handlers(current) if isinstance(current, dict) else []
        if not handlers or not all(is_ours(h, mark) for h in handlers):
            raise ValueError(f'Not created by this script; refusing to replace hook entry {name!r}')


def merge_agy(data, feature=DAILY_LOG):
    """Antigravity: named top-level entries, one event each; keys that are not lists (its
    `enabled` switch) are kept."""
    for event, mode, matcher in feature.events['agy']:
        name = feature.agy_names[mode]
        check_agy_entry(data, name, feature.mark)
        wanted = handler('agy', mode, feature.script, feature.timeout)
        kept = {key: value for key, value in (data.get(name) or {}).items() if not isinstance(value, list)}
        data[name] = {**kept, event: [group([wanted], matcher)] if event in TOOL_EVENTS else [wanted]}


def remove_events(data, cli, feature=DAILY_LOG):
    """Claude Code and Codex: drop our handlers; emptied groups, events, and "hooks" go too."""
    hooks = data.get('hooks')
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    changed = False
    for event, _, _ in feature.events[cli]:
        groups = hooks.get(event)
        if groups is None:
            continue
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        kept, _ = strip_ours(groups, feature.mark)
        if kept == groups:
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if changed and not hooks:
        del data['hooks']


def remove_agy(data, feature=DAILY_LOG):
    for name in feature.agy_names.values():
        check_agy_entry(data, name, feature.mark)
        data.pop(name, None)


def plan_file(home, cli, hook=HOOK, uninstall=False, chosen=None):
    """One file's change for the chosen features (default: daily-log alone, run at `hook`)."""
    chosen = chosen if chosen is not None else [daily_log(hook)]
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
        for feature in chosen:
            if cli == 'agy' and uninstall:
                remove_agy(data, feature)
            elif cli == 'agy':
                merge_agy(data, feature)
            elif uninstall:
                remove_events(data, cli, feature)
            else:
                merge_events(data, cli, feature)
        return old if data == original else (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()

    return installer.edit(path, change)


def install(home, add, remove=(), apply=False, hook=HOOK, chosen=None):
    """Merge the features' hooks into the hook files of the CLIs in `add`; take them out for
    `remove`. One edit per file, whatever the number of features."""
    plans = ([plan_file(home, cli, hook, False, chosen) for cli in add] +
             [plan_file(home, cli, hook, True, chosen) for cli in remove])
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
    return install(home, on, off, write, hook, features(hook))


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('hooks', lambda: run(args.home, args.target, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
