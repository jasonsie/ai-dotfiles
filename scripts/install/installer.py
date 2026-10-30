"""Shared by the install steps: which CLIs to set up, and writing changes safely.

config/ai-clis.json lists each CLI: whether it is on, and where it reads things. The file is
the desired state: a run installs for the CLIs switched on and removes what this repo put
in place for those switched off. --target only narrows a run to one listed CLI. How each
CLI's files are edited (TOML or JSON, `mcp add`, hook events) stays in the steps.

A step plans changes as (path, before, after). A state is ('absent',), ('link', target),
('file', data, mode), or ('other',) for anything else, which is never replaced. apply()
writes every change or none: it refuses a path whose state is no longer `before`, backs
up each file it replaces, sets each path atomically, and on failure puts every changed
path back. What a step may replace, and what it records, stays in the step.

Run directly, it checks config/ai-clis.json and warns when a CLI's folder override
(CLAUDE_CONFIG_DIR, CODEX_HOME, PI_CODING_AGENT_DIR) disagrees with it; the variables
themselves are never read for paths.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REGISTRY = Path(__file__).resolve().parents[2] / 'config/ai-clis.json'
REQUIRED = ('instructions', 'settings', 'mcp', 'skills')
OPTIONAL = ('hooks', 'extensions')  # a CLI lists the ones it has: a hook file, or an extension folder
SUPPORTED = ('claude', 'codex', 'pi', 'agy')  # the CLIs whose formats the steps know
OVERRIDES = {'claude': 'CLAUDE_CONFIG_DIR', 'codex': 'CODEX_HOME', 'pi': 'PI_CODING_AGENT_DIR'}
STATE = '.local/state/ai-dotfiles'  # receipts and backups


def clis():
    """{id: entry} from config/ai-clis.json, checked strictly."""
    data = json.loads(REGISTRY.read_text())
    if data.get('version') != 1 or not isinstance(data.get('clis'), dict):
        raise ValueError(f'{REGISTRY}: expected "version": 1 and a "clis" object')
    for cli, entry in data['clis'].items():
        if cli not in SUPPORTED:
            raise ValueError(f'{REGISTRY}: no installer support for {cli!r} yet')
        if not isinstance(entry, dict) or not isinstance(entry.get('on'), bool):
            raise ValueError(f'{REGISTRY}: {cli} needs "on": true or false')
        missing = [key for key in REQUIRED if key not in entry]
        unknown = sorted(set(entry) - {'name', 'on', *REQUIRED, *OPTIONAL})
        if missing or unknown:
            raise ValueError(f'{REGISTRY}: {cli} ' + ', '.join(
                [f'is missing "{key}"' for key in missing] + [f'has unknown key "{key}"' for key in unknown]))
        for key in (*REQUIRED, *OPTIONAL):
            if key in entry and not (isinstance(entry[key], str) and entry[key].startswith('~/')):
                raise ValueError(f'{REGISTRY}: {cli} "{key}" must be a path starting with ~/')
    return data['clis']


def path(home, cli, kind):
    """Where a CLI reads one kind of file, under `home`; None when it has none."""
    where = clis()[cli].get(kind)
    return home / where[2:] if where else None


def scope(target):
    """The CLIs a --target value selects: one listed CLI, or every listed one for `all`."""
    listed = tuple(clis())
    if target == 'all':
        return listed
    if target not in listed:
        raise ValueError(f'unknown target {target!r}; config/ai-clis.json lists {", ".join(listed)}')
    return (target,)


def split(selected):
    """(on, off): the selected CLIs that config/ai-clis.json switches on, and the others."""
    entries = clis()
    return (tuple(cli for cli in selected if entries[cli]['on']),
            tuple(cli for cli in selected if not entries[cli]['on']))


def check(home):
    """Warnings for a CLI folder override that config/ai-clis.json does not follow."""
    warnings = []
    for cli, variable in OVERRIDES.items():
        value = os.environ.get(variable)
        if value and cli in clis():
            settings = home / clis()[cli]['settings'][2:]
            if not settings.is_relative_to(Path(value).expanduser().resolve()):
                warnings.append(f'Warning: {variable} is {value}, but config/ai-clis.json has {cli} '
                                f'read {settings}; edit the file to match.')
    return warnings


def state(path):
    if path.is_symlink():
        return ('link', os.readlink(path))
    if path.is_file():
        return ('file', path.read_bytes(), path.stat().st_mode & 0o777)
    return ('other',) if path.exists() else ('absent',)


def receipt(data):
    """The file state of a receipt: private JSON."""
    return ('file', (json.dumps(data, indent=2, sort_keys=True) + '\n').encode(), 0o600)


def edit(path, change):
    """(path, before, after) for an in-place edit of a file a CLI owns, or None when
    `change(old bytes)` returns them unchanged. A missing file reads as empty and is
    created private; an existing one keeps its mode; a link or folder there is refused."""
    before = state(path)
    if before[0] == 'link':
        raise ValueError(f'Refusing to write through symlinked file: {path}')
    if before[0] == 'other':
        raise ValueError(f'Not a file: {path}')
    old = before[1] if before[0] == 'file' else b''
    new = change(old)
    if new == old:
        return None
    return path, before, ('file', new, before[2] if before[0] == 'file' else 0o600)


def put(path, wanted):
    """Set one path to a state atomically: build it beside the path, then rename it over."""
    if wanted == ('absent',):
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        new = Path(temp) / 'new'
        if wanted[0] == 'link':
            new.symlink_to(wanted[1])
        else:
            new.write_bytes(wanted[1])
            new.chmod(wanted[2])
        os.replace(new, path)


def apply(home, changes, backup=None):
    """Write every change or none. With `backup` (a folder name under STATE), each file
    about to be replaced is first copied into a new backup-* folder, which is returned."""
    for path, before, after in changes:
        if 'other' in (before[0], after[0]):
            raise ValueError(f'Refusing to replace what is not a file or link: {path}')
        if state(path) != before:
            raise ValueError(f'Concurrent edit detected: {path}')
    saved = None
    files = [(path, before) for path, before, _ in changes if before[0] == 'file']
    if backup and files:
        root = home / STATE / backup
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        saved = Path(tempfile.mkdtemp(prefix='backup-', dir=root))
        for path, before in files:
            put(saved / (path.relative_to(home) if path.is_relative_to(home) else path.name), before)
    done = []
    try:
        for path, before, after in changes:
            if state(path) != before:
                raise ValueError(f'Concurrent edit detected: {path}')
            done.append((path, before))
            put(path, after)
    except BaseException:
        for path, before in reversed(done):
            put(path, before)
        raise
    return saved


def show(changes, write):
    """One line per change: 'Link: path -> target', or 'Would link: …' in a preview."""
    for path, before, after in changes:
        if after[0] == 'link':
            verb, what = 'link', f'{path} -> {after[1]}'
        elif after == ('absent',):
            verb, what = 'remove', path
        else:
            verb, what = 'update' if before[0] == 'file' else 'write', path
        print(f'{verb.capitalize()}: {what}' if write else f'Would {verb}: {what}')


def parser(doc, cli_target=True):
    """The flags every step shares: --home, --target (a listed CLI or all), --dry-run, --uninstall."""
    options = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    options.add_argument('--home', type=lambda p: Path(p).expanduser().resolve(), default=Path.home().resolve(),
                         help='home folder to install into (default: ~)')
    if cli_target:
        options.add_argument('--target', default='all', help='a CLI listed in config/ai-clis.json, or all')
    options.add_argument('--dry-run', action='store_true', help='preview only; write nothing')
    options.add_argument('--uninstall', action='store_true', help='remove what this step installed')
    return options


def finish(step, run):
    """Run a step and print `step: N changes`, which the healthcheck counts; on an error,
    print it and return exit status 1."""
    try:
        count = run()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'{step}: {error}', file=sys.stderr)
        return 1
    print(f'{step}: {count} changes')
    return 0


if __name__ == '__main__':
    try:
        clis()
    except (OSError, ValueError) as error:
        print(f'clis: {error}', file=sys.stderr)
        sys.exit(1)
    for warning in check(Path.home().resolve()):
        print(warning, file=sys.stderr)
