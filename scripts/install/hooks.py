#!/usr/bin/env python3
"""Install the door's hook entries into each CLI, one per event; writes unless --dry-run.

Every CLI reaches the features through one door, `ai-dotfiles hook <kind> --cli <cli>` (lib/door.py),
which runs every feature that wants the event. Each feature says what it wants in its feature.json
(lib/features.py); for each CLI with a hook file this step writes one entry per event any feature
wants there:
  matcher   the union of the features' tools for that event, or none when one wants every call
  timeout   the door's time for that event in that CLI (scripts/agent_hooks.py TIMEOUTS), within the
            CLI's cap, never a feature's budget: a budget changes no entry
  command   ~/.local/bin/ai-dotfiles hook <kind> --cli <cli> || true, which names no file in the
            repo: a feature that moves changes no entry. `|| true`: a missing command or bad
            arguments exit 127 or 2, which the CLIs act on (the error goes to the model; at Stop it
            keeps the turn going). All three run the command in a shell.
Codex trusts a hook by the hash of its entry and runs no new or changed one until the person approves
it in /hooks, so it asks again only when the events or tools the door listens to change.
  Claude Code   ~/.claude/settings.json      "hooks": event -> [{matcher, hooks: [handler]}]
  Codex         ~/.codex/hooks.json          the same shape
  Antigravity   ~/.gemini/config/hooks.json  a named entry per event (ai-dotfiles-hook-pre)
Pi has no hook file: skills.py links scripts/agent_hooks.ts as its extension, which sends each event
to the door. With --cloud (a cloud session's VM) only the features whose declaration says cloud get
entries; the door, which sees CLAUDE_CODE_REMOTE there, runs only those.

The door runs the Python this step ran with (install.sh's, checked to be 3.11+): the step links it as
~/.local/state/ai-dotfiles/python3, and `ai-dotfiles hook` starts that instead of python3. A pyenv
shim on PATH costs about 150 ms per call, and picks the Python of the session's folder, which may be
a project's own: an older one, or one not installed, where it falls back to another. The link
follows each install; while it is missing or broken the door starts python3. Like the commands
skills.py links, it serves every CLI, so only an uninstall of every CLI removes it.

An entry counts as ours when its command runs the door; anything else in its place is refused. An
event no feature wants any more loses its entry. Hooks this script installed before and no longer
does are taken out wherever they are found: each feature's own entries from before the door (found
by its script's path; the door's group takes the place of the first) and daily-log's Stop nudge,
replaced by the daily pass, with its state folder. Files are never written through a symlink, are
backed up before writing, and are restored on failure. --uninstall removes only these entries,
leaving every other hook as it is.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / 'lib'))
import features as declared  # noqa: E402  (each feature's feature.json; it puts scripts/ on the path)
import agent_hooks  # noqa: E402  (the CLIs' hook formats)

TOOL_EVENTS = ('PreToolUse', 'PostToolUse')  # Antigravity: these take matcher groups, the rest bare handlers
DOOR = '~/.local/bin/ai-dotfiles'  # where skills.py links scripts/ai-dotfiles
MARK = f'{DOOR} hook '  # how an entry of ours is known
PYTHON = installer.STATE + '/python3'  # the Python the door starts; scripts/ai-dotfiles reads this path
AGY_NAME = 'ai-dotfiles-hook-'  # + kind: Antigravity's named entries
# Retired, wherever found: each feature's own entries from before the door (November 2026), and the
# daily-log Stop nudge (PostToolUse + Stop in every CLI), replaced by the daily pass that month.
RETIRED_MARKS = ('skills/daily-log/scripts/daily_log.py', 'skills/worktree-guard/scripts/worktree_guard.py',
                 'skills/small-commits/scripts/small_commits.py', 'skills/herdr-title/scripts/herdr_title.py')
RETIRED_AGY = ('ai-dotfiles-daily-log-tool', 'ai-dotfiles-daily-log-stop', 'ai-dotfiles-worktree-guard-pre',
               'ai-dotfiles-small-commits-pre')
RETIRED_STATE = ('.local/state/ai-dotfiles/daily-log',)
OURS = (MARK, *RETIRED_MARKS)


def entries(cli, chosen):
    """((native event, kind, matcher, timeout), ...) for `cli`: one per kind a chosen feature wants
    there. No entry when none of the tools wanted has a matcher in this CLI, not one for every tool;
    none at all for a CLI without a hook file (Pi's extension asks the door itself)."""
    if cli not in agent_hooks.HOOK_FILE_CLIS:
        return ()
    found = []
    for kind in agent_hooks.KINDS[cli]:
        tools = [feature.tools(cli, kind) for feature in chosen if kind in feature.wants.get(cli, {})]
        if not tools:
            continue
        matcher = None
        if all(tool is not None for tool in tools):
            union = set().union(*tools)
            matcher = '|'.join(m for action, m in agent_hooks.MATCHERS[cli].items() if action in union)
            if not matcher:
                continue
        found.append((agent_hooks.NATIVE[kind], kind, matcher, agent_hooks.timeout(cli, kind)))
    return tuple(found)


def handler(cli, kind, timeout):
    return {'type': 'command', 'command': f'{MARK}{kind} --cli {cli} || true', 'timeout': timeout}


def group(handlers, matcher):
    """A matcher group; Stop and the like take no matcher, so the key is left out."""
    return {'matcher': matcher, 'hooks': handlers} if matcher else {'hooks': handlers}


def is_ours(entry, marks=OURS):
    return isinstance(entry, dict) and any(mark in str(entry.get('command', '')) for mark in marks)


def holds_ours(item, marks=OURS):
    inner = item.get('hooks') if isinstance(item, dict) else None
    return isinstance(inner, list) and any(is_ours(h, marks) for h in inner)


def strip_ours(groups, marks=OURS):
    """(groups without our handlers, where the first group that held one stood, or None).
    A foreign handler that shares a group with ours stays, in a group of its own."""
    kept, at = [], None
    for item in groups:
        if not holds_ours(item, marks):
            kept.append(item)
            continue
        if at is None:
            at = len(kept)
        rest = [h for h in item['hooks'] if not is_ours(h, marks)]
        if rest:
            kept.append({**item, 'hooks': rest})
    return kept, at


def hook_table(data):
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    return hooks


def merge_events(data, cli, wanted):
    """Claude Code and Codex: event -> [{matcher, hooks: [handler]}]. The door's group takes the
    place of the first one that held ours (the door's, or a retired entry's), or is appended; every
    other group and handler stays."""
    if not wanted:
        return
    hooks = hook_table(data)
    for event, kind, matcher, timeout in wanted:
        groups = hooks.get(event)
        if groups is None:
            groups = []
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        kept, at = strip_ours(groups)
        kept.insert(len(kept) if at is None else at, group([handler(cli, kind, timeout)], matcher))
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


def check_agy_entry(data, name, marks=(MARK,)):
    current = data.get(name)
    if current is not None:
        handlers = agy_handlers(current) if isinstance(current, dict) else []
        if not handlers or not all(is_ours(h, marks) for h in handlers):
            raise ValueError(f'Not created by this script; refusing to replace hook entry {name!r}')


def merge_agy(data, wanted):
    """Antigravity: named top-level entries, one event each; keys that are not lists (its
    `enabled` switch) are kept."""
    for event, kind, matcher, timeout in wanted:
        name = AGY_NAME + kind
        check_agy_entry(data, name)
        door = handler('agy', kind, timeout)
        kept = {key: value for key, value in (data.get(name) or {}).items() if not isinstance(value, list)}
        data[name] = {**kept, event: [group([door], matcher)] if event in TOOL_EVENTS else [door]}


def drop_emptied(data, hooks, changed):
    if changed and not hooks:
        del data['hooks']


def retire(data, cli, wanted=()):
    """Take out what is ours and not `wanted`, wherever it stands: in a Claude Code or Codex file,
    retired hooks in every event and the door's in each event not wanted; in Antigravity's, the
    door's named entries for kinds not wanted and the retired names (left alone when a hand-made
    entry took the name)."""
    if cli == 'agy':
        keep = {AGY_NAME + kind for _, kind, _, _ in wanted}
        for name in [name for name in data if name.startswith(AGY_NAME) and name not in keep]:
            check_agy_entry(data, name)
            del data[name]
        for name in RETIRED_AGY:
            entry = data.get(name)
            handlers = agy_handlers(entry) if isinstance(entry, dict) else []
            if handlers and all(is_ours(h, RETIRED_MARKS) for h in handlers):
                del data[name]
        return
    hooks = data.get('hooks')
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    keep = {event for event, _, _, _ in wanted}
    changed = False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept, _ = strip_ours(groups, RETIRED_MARKS if event in keep else OURS)
        if kept == groups:
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    drop_emptied(data, hooks, changed)


def retired_state(home):
    return [home / folder for folder in RETIRED_STATE if (home / folder).is_dir()]


def plan_file(home, cli, chosen, uninstall=False):
    """(path, before, after) for one CLI's hook file, or None when nothing changes."""
    path = installer.path(home, cli, 'hooks')
    if path is None:
        return None  # no hook file: Pi takes an extension, linked by skills.py
    if cli not in agent_hooks.HOOK_FILE_CLIS:
        raise ValueError(f'No hook format for {cli} yet; add it to scripts/agent_hooks.py')
    if not path.parent.is_dir():
        return None  # CLI not set up on this machine
    wanted = () if uninstall else entries(cli, chosen)

    def change(old):
        original = json.loads(old) if old.strip() else {}
        if not isinstance(original, dict):
            raise ValueError(f'{path}: expected a JSON object')
        data = copy.deepcopy(original)
        if cli == 'agy':
            merge_agy(data, wanted)
        else:
            merge_events(data, cli, wanted)
        retire(data, cli, wanted)
        return old if data == original else (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()

    return installer.edit(path, change)


def plan_python(home, uninstall=False):
    """(path, before, after) for the link to the Python the door starts, or None when it is as wanted."""
    path = home / PYTHON
    before = installer.state(path)
    after = ('absent',) if uninstall or not sys.executable else ('link', sys.executable)
    if before == after:
        return None
    if before[0] not in ('absent', 'link'):
        raise ValueError(f'Not created by this script; refusing to replace: {path}')
    return path, before, after


def install(home, add, remove=(), apply=False, chosen=None, python: bool | None = True):
    """Merge the door's entries for the chosen features into the hook files of the CLIs in `add`;
    take ours out for `remove`; retire what is no longer installed. One edit per file. `python`:
    link the door's Python (True), remove the link (False), or leave it as it is (None)."""
    chosen = declared.find() if chosen is None else chosen
    plans = ([plan_file(home, cli, chosen) for cli in add] +
             [plan_file(home, cli, chosen, True) for cli in remove] +
             ([] if python is None else [plan_python(home, uninstall=not python)]))
    changes = [change for change in plans if change]
    installer.show(changes, apply)
    if apply and changes:
        print(f'Backup: {installer.apply(home, changes, backup="settings")}')
        if 'codex' in add and any(path == installer.path(home, 'codex', 'hooks') for path, _, _ in changes):
            print('Codex: approve the new hooks once with /hooks; Codex runs no unreviewed hook.')
    folders = retired_state(home)
    for folder in folders:
        print(f'Remove folder: {folder}' if apply else f'Would remove folder: {folder}')
        if apply:
            shutil.rmtree(folder, ignore_errors=True)
    return len(changes) + len(folders)


def run(home, target, write, uninstall, repo=WORKSPACE, cloud=False):
    """Hooks for the CLIs switched on; none for those switched off, or for any on --uninstall. The
    door's Python is linked on every install, and its link removed only with every CLI's hooks."""
    selected = installer.scope(target)
    on, off = ((), selected) if uninstall else installer.split(selected)
    python = None if uninstall and set(selected) != set(installer.clis()) else not uninstall
    chosen = [feature for feature in declared.find(repo) if feature.cloud or not cloud]
    return install(home, on, off, write, chosen, python)


def main():
    options = installer.parser(__doc__)
    options.add_argument('--cloud', action='store_true', help="a cloud session's VM: the cloud features alone")
    args = options.parse_args()
    return installer.finish('hooks', lambda: run(args.home, args.target, not args.dry_run, args.uninstall,
                                                 cloud=args.cloud))


if __name__ == '__main__':
    sys.exit(main())
