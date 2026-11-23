#!/usr/bin/env python3
"""Link skills, the ai-dotfiles and daily-log commands, and Pi's hooks extension; writes unless --dry-run.

Every folder under skills/ that has a SKILL.md, or sits in a bundle folder (skills/git/)
one level down, is linked by name into the skill folder of each CLI that config/ai-clis.json switches on. A folder several CLIs read
(~/.agents/skills, for Codex and Pi) stays linked while any of them is on; a folder only
switched-off CLIs read loses its links. scripts/ai-dotfiles and the daily-log skill's
script are linked as ~/.local/bin/ai-dotfiles and ~/.local/bin/daily-log, so both commands
work from any folder; shell files are never edited, and a hint is printed when that folder
is not on PATH. Pi has no hooks, so while it is on and set up it gets scripts/agent_hooks.ts,
which sends each event to the door (`ai-dotfiles hook`), in its extensions folder; the
daily-log-only extension it used to link is removed.

With --cloud (a cloud session's VM, set up by scripts/cloud/setup.sh) it leaves out the skills
config/cloud.json keeps local, and any command named after one (daily-log).

An existing entry this script did not create is refused, unless it already is the wanted
link. A link it created that is no longer wanted is removed; a link the user changed is
left alone. A receipt records what it owns, and a failed run restores every link it
changed. --uninstall removes the links it owns for the selected CLIs, keeping a shared
folder another CLI still reads; the commands, which serve them all, go only with
--target=all.
"""
import json
import os
from pathlib import Path
import sys

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
RECEIPT = installer.STATE + '/skills.json'
BIN = '.local/bin'
COMMANDS = {  # name in BIN -> its target in this repo
    'ai-dotfiles': 'scripts/ai-dotfiles',
    'daily-log': 'skills/daily-log/scripts/daily_log.py',
}
COMMAND_RECEIPT = installer.STATE + '/command.json'  # left by install-command.py, which this replaced
PI_EXTENSION = 'ai-dotfiles-hooks.ts'
PI_EXTENSION_TARGET = 'scripts/agent_hooks.ts'
PI_RETIRED = ('ai-dotfiles-daily-log.ts',)  # extensions this script linked before; removed when found
CLOUD = 'config/cloud.json'  # local_only: the skills a cloud session's VM leaves out, each with why


def skills(source):
    """{name: folder} of every skill in this repo, a bundle's (skills/git/) flattened by name.

    The CLIs read one level of skill folders, so a bundle is the repo's grouping only: each
    skill in it is linked by its own name, and two skills with one name are refused.
    """
    found = {}
    tops = sorted(p for p in source.iterdir() if p.is_dir()) if source.is_dir() else []
    for top in tops:
        inner = [top] if (top / 'SKILL.md').is_file() else sorted(
            c for c in top.iterdir() if (c / 'SKILL.md').is_file())
        for folder in inner:
            if folder.name in found:
                raise ValueError(f'Two skills named {folder.name}: {found[folder.name]} and {folder}')
            found[folder.name] = folder
    return found


def local_only(workspace):
    """{skill: why it stays on the Mac} from config/cloud.json."""
    return json.loads((Path(workspace) / CLOUD).read_text())['local_only']


def cloud_skills(workspace):
    """{name: folder} of the skills a cloud session gets: every skill but config/cloud.json's local_only."""
    local = local_only(workspace)
    return {name: folder for name, folder in skills(Path(workspace) / 'skills').items() if name not in local}


def owns_commands(selected, uninstall):
    """The commands serve every CLI: each install links them; only a full uninstall removes them."""
    return not uninstall or set(selected) == set(installer.clis())


def plan(home, selected, workspace, owned, uninstall=False, live=None, cloud=False):
    """Link changes for the selected CLIs, and the receipt's next list of owned links. Skills are found
    in `workspace`; every link names the same path under `live` (installer.live_root), the workspace
    when not given. `cloud` leaves out config/cloud.json's local_only skills and their commands."""
    live = live or workspace
    local = local_only(workspace) if cloud else {}
    entries = installer.clis()
    roots = {installer.path(home, cli, 'skills') for cli in selected}
    # A folder stays linked while a CLI switched on reads it, unless this run uninstalls that CLI.
    keep = {installer.path(home, cli, 'skills') for cli, entry in entries.items()
            if entry['on'] and not (uninstall and cli in selected)}
    link_roots = set() if uninstall else roots & keep
    managed_roots = link_roots | (roots - keep)
    commands = {str(home / BIN / name): str(live / target) for name, target in COMMANDS.items()
                if name not in local}
    others = set(commands) if owns_commands(selected, uninstall) else set()
    extensions = installer.path(home, 'pi', 'extensions') if 'pi' in selected else None
    extension = str(extensions / PI_EXTENSION) if extensions else None
    if extension:
        others.add(extension)
        others.update(str(extensions / name) for name in PI_RETIRED)
    chosen = lambda path: Path(path).parent in managed_roots or path in others  # noqa: E731
    desired = {}
    if link_roots:
        found = skills(workspace / 'skills')
        desired = {str(root / name): str(live / folder.relative_to(workspace))
                   for root in sorted(link_roots) for name, folder in found.items() if name not in local}
    if not uninstall:
        desired.update(commands)
        if extension and entries['pi']['on'] and Path(extension).parent.parent.is_dir():
            desired[extension] = str(live / PI_EXTENSION_TARGET)
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


def install(home, selected, workspace=WORKSPACE, apply=False, uninstall=False, path_env=None, live=None,
            cloud=False):
    receipt = home / RECEIPT
    owned = json.loads(receipt.read_text())['links'] if receipt.is_file() else {}
    changes, links = plan(home, selected, workspace, owned, uninstall, live, cloud)
    if links != owned:
        changes.append((receipt, installer.state(receipt), installer.receipt({'version': 1, 'links': links})))
    old = home / COMMAND_RECEIPT
    if old.exists() and owns_commands(selected, uninstall):
        changes.append((old, installer.state(old), ('absent',)))
    installer.show(changes, apply)
    if apply and changes:
        installer.apply(home, changes)
    folder = str(home / BIN)
    entries = (os.environ.get('PATH', '') if path_env is None else path_env).split(os.pathsep)
    if not uninstall and folder not in (e.rstrip('/') for e in entries):
        print(f'Hint: add {folder} to PATH to run {" and ".join(COMMANDS)} from any folder.')
    return len(changes)


def main():
    options = installer.parser(__doc__)
    options.add_argument('--cloud', action='store_true',
                         help="a cloud session's VM: leave out the skills config/cloud.json keeps local")
    args = options.parse_args()
    return installer.finish('skills', lambda: install(
        args.home, installer.scope(args.target), apply=not args.dry_run, uninstall=args.uninstall,
        live=installer.live_root(WORKSPACE), cloud=args.cloud))


if __name__ == '__main__':
    sys.exit(main())
