#!/usr/bin/env python3
"""Link the `ai-dotfiles` command into ~/.local/bin; writes unless --dry-run.

The link points at scripts/ai-dotfiles in this checkout, so the command works from any
folder. An existing entry this script did not create is refused; its own link is
replaced when the repository moved. A receipt records what it owns, --uninstall
removes only that link, and a failed run restores the previous link. Shell files are
never edited: when ~/.local/bin is not on PATH, a hint is printed instead.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
COMMAND = WORKSPACE / 'scripts/ai-dotfiles'
LINK = '.local/bin/ai-dotfiles'
RECEIPT = '.local/state/ai-dotfiles/command.json'


def state(path):
    if path.is_symlink():
        return ('link', os.readlink(path))
    return ('other',) if path.exists() else ('absent',)


def set_state(path, wanted):
    if wanted == ('absent',):
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        link = Path(temp) / 'link'
        link.symlink_to(wanted[1])
        os.replace(link, path)


def write_receipt(home, owned):
    path = home / RECEIPT
    if owned is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        json.dump({'version': 1, 'link': str(home / LINK), 'target': owned}, f, indent=2)
        f.write('\n')
    os.chmod(f.name, 0o600)
    os.replace(f.name, path)


def plan(home, command, uninstall):
    """(link path, current state, wanted state, receipt target), or None when nothing changes."""
    path = home / LINK
    receipt = home / RECEIPT
    owned = json.loads(receipt.read_text())['target'] if receipt.is_file() else None
    current = state(path)
    if uninstall:
        if owned is None:
            return None
        if current == ('link', owned):
            return path, current, ('absent',), None
        return path, current, current, None  # the user changed it: forget it, leave it
    wanted = ('link', str(command))
    if current == wanted and owned == wanted[1]:
        return None
    if current not in (('absent',), wanted) and not (owned and current[0] == 'link'):
        raise ValueError(f'Not created by this script; refusing to replace: {path}')
    return path, current, wanted, wanted[1]


def install(home, command=COMMAND, apply=False, uninstall=False, path_env=None):
    change = plan(home, command, uninstall)
    if change:
        path, before, after, _ = change
        if after == before:
            print(f'{"Forget" if apply else "Would forget"}: {path} (changed by you; left as is)')
        elif after[0] == 'link':
            print(f'{"Link" if apply else "Would link"}: {path} -> {after[1]}')
        else:
            print(f'{"Remove" if apply else "Would remove"}: {path}')
        if apply:
            if state(path) != before:
                raise ValueError(f'Concurrent edit detected: {path}')
            set_state(path, after)
            try:
                write_receipt(home, change[3])
            except BaseException:
                set_state(path, before)
                raise
    folder = str((home / LINK).parent)
    entries = (os.environ.get('PATH', '') if path_env is None else path_env).split(os.pathsep)
    if not uninstall and folder not in (e.rstrip('/') for e in entries):
        print(f'Hint: add {folder} to PATH to run ai-dotfiles from any folder.')
    return int(change is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--dry-run', action='store_true', help='preview only; write nothing')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    try:
        count = install(args.home.expanduser().resolve(), apply=not args.dry_run, uninstall=args.uninstall)
    except (OSError, ValueError, KeyError) as e:
        print(f'command: {e}', file=sys.stderr)
        return 1
    print(f'command: {count} changes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
