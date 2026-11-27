#!/usr/bin/env python3
"""Link CLI-global instructions to one source, config/global-agents.md; writes unless --dry-run.

Only instruction entry files are changed, never settings, credentials, or hooks.
Unknown existing instructions require --replace-existing and are backed up.
--uninstall removes our links and restores the earliest backed-up original (skipping
empty files, tool-written blocks only, and `@` imports of files now gone).
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
SOURCE = "config/global-agents.md"
OLD_SOURCE = "tools/instructions/AGENTS.md"  # where the source lived before config/; a link there is ours
BACKUPS = installer.STATE + "/global-instructions"
TOOL_BLOCK = re.compile(r"<!-- ([\w-]+):start -->.*?<!-- \1:end -->", re.S)


def stale(saved):
    """An original not worth restoring: empty, only tool-written `<!-- x:start/end -->`
    blocks (e.g. an old zkfy block), or only an `@` import of a file now gone."""
    text = TOOL_BLOCK.sub("", saved.read_text(errors="replace")).strip()
    if not text:
        return True
    return "\n" not in text and text.startswith("@") and not Path(text[1:]).expanduser().exists()


def original_record(backup_root, path):
    """Earliest backup record for path whose original was not our own link or stale."""
    manifests = sorted(
        backup_root.glob("backup-*/manifest.json"), key=lambda m: m.stat().st_mtime_ns
    )
    for manifest in manifests:
        for record in json.loads(manifest.read_text()):
            if record["target"] != str(path):
                continue
            saved = manifest.parent / record["backup"] if record["backup"] else None
            if (
                record["original_kind"] == "link"
                and saved is not None
                and os.readlink(saved).endswith((SOURCE, OLD_SOURCE))
            ):
                continue
            if record["original_kind"] == "file" and saved is not None and stale(saved):
                continue
            return record["original_kind"], saved
    return None


def save(home, entries):
    """Copy each (cli, path, state) into a new backup-* folder listed by its manifest.json."""
    root = home / BACKUPS
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="backup-", dir=root))
    records = []
    for cli, path, before in entries:
        name = cli if before != ("absent",) else None
        if name:
            installer.put(backup / name, before)
        records.append({"target": str(path), "original_kind": before[0], "backup": name})
    (backup / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    return backup


def uninstall(home, clis, *, workspace=WORKSPACE, apply=False, live=None):
    home = home.expanduser().resolve()
    source = Path(live or workspace).resolve() / SOURCE  # what our links name
    changes = []  # (cli, path, our link, the original to restore)
    for cli in clis:
        path = installer.path(home, cli, "instructions")
        ours = path.is_symlink() and (path.resolve() == source.resolve() or os.readlink(path).endswith(OLD_SOURCE))
        if not ours:
            if path.is_symlink() or path.exists():
                print(f"Unchanged: {path}")
            continue
        kind, saved = original_record(home / BACKUPS, path) or ("absent", None)
        original = installer.state(saved) if kind != "absent" and saved else ("absent",)
        changes.append((cli, path, installer.state(path), original))
    installer.show([change[1:] for change in changes], apply)
    if apply and changes:
        print(f"Backup: {save(home, [change[:3] for change in changes])}")
        installer.apply(home, [change[1:] for change in changes])
    return len(changes)


def install(home, clis, *, workspace=WORKSPACE, apply=False, replace_existing=False, live=None):
    """Link each CLI's instructions to `live` (installer.live_root; the workspace when not given)
    after checking the workspace's copy."""
    home, workspace = home.expanduser().resolve(), workspace.resolve()
    source = workspace / SOURCE
    if not source.is_file():  # an empty file is valid: no shared instructions
        raise ValueError(f"Missing shared instructions: {source}")
    if source.stat().st_size >= 32 * 1024:
        raise ValueError(
            "Shared instructions must stay below Codex's 32 KiB default limit"
        )
    target = Path(live or workspace).resolve() / SOURCE  # what the links name
    changes = []  # (cli, path, state before)
    for cli in clis:
        path = installer.path(home, cli, "instructions")
        if not path.is_symlink() and path.resolve() in (source.resolve(), target.resolve()):
            raise ValueError(f"Instruction destination is the shared source: {path}")
        for parent in path.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"Instruction parent is not a directory: {parent}")
        if cli in ("codex", "pi"):
            override = path.with_name("AGENTS.override.md")
            if override.is_file() and override.read_text().strip():
                raise ValueError(
                    f"{override} shadows shared instructions; resolve it before installation"
                )
        if path.is_symlink() and path.resolve() == target.resolve():
            print(f"Unchanged: {path}")
            continue
        before = installer.state(path)
        if before == ("other",):
            raise ValueError(f"Refusing to replace a non-file: {path}")
        empty = before[0] == "file" and not before[1].strip()
        moved = before[0] == "link" and before[1].endswith(OLD_SOURCE)
        if before != ("absent",) and not empty and not moved and not replace_existing:
            raise ValueError(
                f"Existing instructions at {path}; review them and use --replace-existing to migrate"
            )
        changes.append((cli, path, before))

    # Every destination is validated before any of them is touched.
    link = [(path, before, ("link", str(target))) for _, path, before in changes]
    installer.show(link, apply)
    if apply and changes:
        print(f"Backup: {save(home, changes)}")
        installer.apply(home, link)
    return len(changes)


def run(home, target, write, uninstall_all, replace_existing, workspace=WORKSPACE, live=None):
    """Link the CLIs switched on and unlink those switched off; --uninstall unlinks all."""
    selected = installer.scope(target)
    if uninstall_all:
        return uninstall(home, selected, workspace=workspace, apply=write, live=live)
    on, off = installer.split(selected)
    return (install(home, on, workspace=workspace, apply=write, replace_existing=replace_existing, live=live)
            + uninstall(home, off, workspace=workspace, apply=write, live=live))


SUMMARY = "config/global-agents.md → each CLI's global entry (symlink)"
UNDO = 'links removed; the file from before the first install is restored'


def execute(options):
    """The step as lib/install/run.py runs it: the number of changes."""
    return run(options.home, options.target, options.apply, options.uninstall, options.replace_instructions,
               live=options.live)


def main():
    parser = installer.parser(__doc__)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    return installer.finish("instructions", lambda: run(
        args.home, args.target, not args.dry_run, args.uninstall, args.replace_existing,
        live=installer.live_root(WORKSPACE)))


if __name__ == "__main__":
    sys.exit(main())
