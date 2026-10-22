#!/usr/bin/env python3
"""Link skills and the ai-dotfiles command; writes unless --dry-run.

Every folder under skills/ that has a SKILL.md, plus zkfy's `query` skill when this machine
has a zkfy checkout (ZKFY_DIR, or the one the vault binding names), is linked by name into
the skill folder of each CLI that config/ai-clis.json switches on. A folder several CLIs
read (~/.agents/skills, for Codex and Pi) stays linked while any of them is on; a folder
only switched-off CLIs read loses its links. scripts/ai-dotfiles is linked as
~/.local/bin/ai-dotfiles, so the command works from any folder; shell files are never
edited, and a hint is printed when that folder is not on PATH.

An existing entry this script did not create is refused, unless it already is the wanted
link. A link it created that is no longer wanted is removed; a link the user changed is
left alone. A receipt records what it owns, and a failed run restores every link it
changed. --uninstall removes the links it owns for the selected CLIs, keeping a shared
folder another CLI still reads; the command, which serves them all, goes only with
--target=all.
"""
import json
import os
from pathlib import Path
import sys

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
RECEIPT = installer.STATE + '/skills.json'
COMMAND = '.local/bin/ai-dotfiles'
COMMAND_RECEIPT = installer.STATE + '/command.json'  # left by install-command.py, which this replaced


def skills(source, zkfy=None):
    """{name: folder} of every skill to link: this repo's, and zkfy's `query` when given."""
    found = {p.name: p for p in sorted(source.iterdir()) if (p / 'SKILL.md').is_file()} if source.is_dir() else {}
    if zkfy is not None:
        if 'query' in found:
            raise ValueError("skills/query would hide zkfy's query skill")
        if not (zkfy / 'skills/query/SKILL.md').is_file():
            raise ValueError(f'Missing the query skill in {zkfy}')
        found['query'] = zkfy / 'skills/query'
    return found


def owns_command(selected, uninstall):
    """The command serves every CLI: each install links it; only a full uninstall removes it."""
    return not uninstall or set(selected) == set(installer.clis())


def plan(home, selected, workspace, zkfy, owned, uninstall=False):
    """Link changes for the selected CLIs, and the receipt's next list of owned links."""
    entries = installer.clis()
    roots = {installer.path(home, cli, 'skills') for cli in selected}
    # A folder stays linked while a CLI switched on reads it, unless this run uninstalls that CLI.
    keep = {installer.path(home, cli, 'skills') for cli, entry in entries.items()
            if entry['on'] and not (uninstall and cli in selected)}
    link_roots = set() if uninstall else roots & keep
    managed_roots = link_roots | (roots - keep)
    command = str(home / COMMAND)
    others = {command} if owns_command(selected, uninstall) else set()
    chosen = lambda path: Path(path).parent in managed_roots or path in others  # noqa: E731
    desired = {}
    if link_roots:
        found = skills(workspace / 'skills', zkfy)
        desired = {str(root / name): str(folder) for root in sorted(link_roots) for name, folder in found.items()}
    if not uninstall:
        desired[command] = str(workspace / 'scripts/ai-dotfiles')
    changes = []
    for path, target in desired.items():
        current = installer.state(Path(path))
        if current == ('link', target):
            continue
        if current != ('absent',) and not (path in owned and current[0] == 'link'):
            raise ValueError(f'Not created by this script; refusing to replace: {path}')
        changes.append((Path(path), current, ('link', target)))
    for path, target in owned.items():
        if path not in desired and chosen(path) and installer.state(Path(path)) == ('link', target):
            changes.append((Path(path), ('link', target), ('absent',)))
    links = {path: target for path, target in owned.items() if not chosen(path)}
    links.update(desired)
    return changes, links


def install(home, selected, workspace=WORKSPACE, zkfy=None, apply=False, uninstall=False, path_env=None):
    receipt = home / RECEIPT
    owned = json.loads(receipt.read_text())['links'] if receipt.is_file() else {}
    changes, links = plan(home, selected, workspace, zkfy, owned, uninstall)
    if links != owned:
        changes.append((receipt, installer.state(receipt), installer.receipt({'version': 1, 'links': links})))
    old = home / COMMAND_RECEIPT
    if old.exists() and owns_command(selected, uninstall):
        changes.append((old, installer.state(old), ('absent',)))
    installer.show(changes, apply)
    if apply and changes:
        installer.apply(home, changes)
    folder = str((home / COMMAND).parent)
    entries = (os.environ.get('PATH', '') if path_env is None else path_env).split(os.pathsep)
    if not uninstall and folder not in (e.rstrip('/') for e in entries):
        print(f'Hint: add {folder} to PATH to run ai-dotfiles from any folder.')
    return len(changes)


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('skills', lambda: install(
        args.home, installer.scope(args.target), zkfy=None if args.uninstall else installer.zkfy_dir(args.home),
        apply=not args.dry_run, uninstall=args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
