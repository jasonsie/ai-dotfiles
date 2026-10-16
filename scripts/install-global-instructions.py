#!/usr/bin/env python3
"""Link CLI-global instructions to one source; dry-run unless --apply.

Only instruction entry files are changed, never settings, credentials, or hooks.
Unknown existing instructions require --replace-existing and are backed up.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
ENTRIES = {
    "claude": (".claude", "CLAUDE.md"),
    "gemini": (".gemini", "GEMINI.md"),
    "codex": (".codex", "AGENTS.md"),
    "pi": (".pi/agent", "AGENTS.md"),
}


def snapshot(path):
    if path.is_symlink():
        return ("link", os.readlink(path))
    if not path.exists():
        return ("absent",)
    if not path.is_file():
        raise ValueError(f"Refusing to replace a non-file: {path}")
    return ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))


def replace_link(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        link = Path(temp) / "entry"
        link.symlink_to(source)
        os.replace(link, path)


def restore_entry(path, saved):
    if saved is None:
        path.unlink(missing_ok=True)
        return
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        entry = Path(temp) / "entry"
        shutil.copy2(saved, entry, follow_symlinks=False)
        os.replace(entry, path)


def install(
    home,
    targets,
    *,
    workspace=WORKSPACE,
    apply=False,
    replace_existing=False,
    config_dirs=None,
):
    home, workspace = home.expanduser().resolve(), workspace.resolve()
    source = workspace / "tools/instructions/AGENTS.md"
    if not source.is_file():  # an empty file is valid: no shared instructions
        raise ValueError(f"Missing shared instructions: {source}")
    if source.stat().st_size >= 32 * 1024:
        raise ValueError(
            "Shared instructions must stay below Codex's 32 KiB default limit"
        )
    config_dirs = config_dirs or {}
    changes = []
    for target in targets:
        directory, filename = ENTRIES[target]
        path = (
            Path(config_dirs.get(target, home / directory)).expanduser().absolute()
            / filename
        )
        if not path.is_symlink() and path.resolve() == source.resolve():
            raise ValueError(f"Instruction destination is the shared source: {path}")
        for parent in path.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"Instruction parent is not a directory: {parent}")
        if target in ("codex", "pi"):
            override = path.with_name("AGENTS.override.md")
            if override.is_file() and override.read_text().strip():
                raise ValueError(
                    f"{override} shadows shared instructions; resolve it before installation"
                )
        before = snapshot(path)
        if path.is_symlink() and path.resolve() == source.resolve():
            print(f"Unchanged: {path}")
            continue
        legacy = (
            target == "claude"
            and before[0] == "file"
            and before[1].strip() == (f"@{workspace}/CLAUDE.md".encode())
        )
        empty = before[0] == "file" and not before[1].strip()
        if before[0] != "absent" and not empty and not legacy and not replace_existing:
            raise ValueError(
                f"Existing instructions at {path}; review them and use --replace-existing to migrate"
            )
        changes.append((target, path, before))

    # Validate every destination before touching any of them.
    for _, path, _ in changes:
        print(f"{'Link' if apply else 'Would link'}: {path} -> {source}")
    if not apply or not changes:
        print(f"{'Applied' if apply else 'Dry-run'}: {len(changes)} changes")
        return len(changes)

    backup_root = home / ".local/state/ai-cli-workspace/global-instructions"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="backup-", dir=backup_root))
    records = []
    for target, path, before in changes:
        saved = backup / target if before[0] != "absent" else None
        if saved is not None:
            if before[0] == "link":
                saved.symlink_to(before[1])
            else:
                saved.write_bytes(before[1])
                saved.chmod(before[2])
        records.append(
            {
                "target": str(path),
                "original_kind": before[0],
                "backup": saved.name if saved else None,
            }
        )
    (backup / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Backup: {backup}")
    done = []
    try:
        for (_, path, before), record in zip(changes, records):
            if snapshot(path) != before:
                raise ValueError(f"Concurrent edit detected: {path}")
            done.append((path, backup / record["backup"] if record["backup"] else None))
            replace_link(path, source)
    except BaseException:
        for path, saved in reversed(done):
            restore_entry(path, saved)
        raise
    print(f"Applied: {len(changes)} changes")
    return len(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        help="Isolated home directory (ignores config-dir environment overrides)",
    )
    parser.add_argument("--target", choices=("all", *ENTRIES), default="all")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    config_dirs = {}
    if args.home is None:
        for target, variable in (
            ("claude", "CLAUDE_CONFIG_DIR"),
            ("codex", "CODEX_HOME"),
            ("pi", "PI_CODING_AGENT_DIR"),
        ):
            if os.environ.get(variable):
                config_dirs[target] = os.environ[variable]
    try:
        install(
            args.home or Path.home(),
            tuple(ENTRIES) if args.target == "all" else (args.target,),
            apply=args.apply,
            replace_existing=args.replace_existing,
            config_dirs=config_dirs,
        )
    except (OSError, ValueError) as error:
        print(f"global instructions: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
