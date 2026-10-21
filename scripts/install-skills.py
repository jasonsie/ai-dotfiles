#!/usr/bin/env python3
"""Link this repository's skills into each CLI's skill folder; writes unless --dry-run.

Every folder under skills/ that has a SKILL.md is linked by name into
~/.claude/skills (Claude Code), ~/.agents/skills (read by Codex and Pi), and
~/.gemini/config/skills (Antigravity CLI and IDE). An existing entry this script
did not create is refused. A link it created for a skill that has since left
skills/ is removed; a link the user changed is left alone. A receipt records
what it owns, and a failed run restores every link it changed. --uninstall removes
every link it owns in the selected folders.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / 'skills'
ROOTS = {
    'claude': '.claude/skills',
    'agents': '.agents/skills',
    'agy': '.gemini/config/skills',
}
RECEIPT = '.local/state/ai-dotfiles/skills.json'


def repo_skills(source):
    if source is None or not source.is_dir():
        return []
    return sorted(p.name for p in source.iterdir() if (p / 'SKILL.md').is_file())


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
        link.symlink_to(wanted[1], target_is_directory=True)
        os.replace(link, path)


def plan(home, targets, source, owned):
    """Link changes for the selected roots, and the receipt's next list of owned links."""
    roots = [home / ROOTS[target] for target in targets]
    selected = lambda path: Path(path).parent in roots  # noqa: E731
    desired = {str(root / name): str(source / name) for root in roots for name in repo_skills(source)}
    changes = []
    for path, target in desired.items():
        current = state(Path(path))
        if current == ('link', target):
            continue
        if current != ('absent',) and not (path in owned and current[0] == 'link'):
            raise ValueError(f'Not created by this script; refusing to replace: {path}')
        changes.append((Path(path), current, ('link', target)))
    for path, target in owned.items():
        if path not in desired and selected(path) and state(Path(path)) == ('link', target):
            changes.append((Path(path), ('link', target), ('absent',)))
    links = {path: target for path, target in owned.items() if not selected(path)}
    links.update(desired)
    return changes, links


def write_receipt(home, links):
    path = home / RECEIPT
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        json.dump({'version': 1, 'links': links}, f, indent=2, sort_keys=True)
        f.write('\n')
    os.chmod(f.name, 0o600)
    os.replace(f.name, path)


def run(home, changes, links):
    done = []
    try:
        for path, before, after in changes:
            if state(path) != before:
                raise ValueError(f'Concurrent edit detected: {path}')
            done.append((path, before))
            set_state(path, after)
        write_receipt(home, links)
    except BaseException:
        for path, before in reversed(done):
            set_state(path, before)
        raise


def install(home, targets, source=SOURCE, apply=False, uninstall=False):
    receipt = home / RECEIPT
    owned = json.loads(receipt.read_text())['links'] if receipt.is_file() else {}
    # Uninstall is an install of no skills: every owned link in the selected folders goes.
    changes, links = plan(home, targets, None if uninstall else source, owned)
    for path, _, after in changes:
        if after[0] == 'link':
            print(f'{"Link" if apply else "Would link"}: {path} -> {after[1]}')
        else:
            print(f'{"Remove" if apply else "Would remove"}: {path}')
    receipt_changes = links != owned
    if receipt_changes:
        print(f'{"Update" if apply else "Would update"}: {receipt}')
    if apply and (changes or receipt_changes):
        run(home, changes, links)
    return len(changes) + receipt_changes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--target', choices=('all', *ROOTS), default='all')
    parser.add_argument('--dry-run', action='store_true', help='preview only; write nothing')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    write = not args.dry_run
    targets = tuple(ROOTS) if args.target == 'all' else (args.target,)
    try:
        count = install(args.home.expanduser().resolve(), targets, SOURCE, write, args.uninstall)
    except (OSError, ValueError, KeyError) as e:
        print(f'skills: {e}', file=sys.stderr)
        return 1
    print(f'skills: {count} changes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
