#!/usr/bin/env python3
"""Bind the zkfy vault tooling for Claude, Codex, Pi and Antigravity; dry-run unless --apply.

Installs exactly five artifacts: the launcher binding (~/.config/zkfy/knowledge.json),
the `vault-knowledge` launcher link, and three `query` skill links: ~/.claude/skills
for Claude, ~/.agents/skills, which Codex and Pi both read, and ~/.gemini/config/skills,
Antigravity's machine-wide root shared by its CLI and IDE.
Retrieval guidance lives in the skill itself; instruction files are never touched
here. A receipt records prior state so --uninstall restores it exactly.

Paths come from --vault/--zkfy, then ZKFY_VAULT/ZKFY_DIR, then the existing binding.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tempfile

RECEIPT = ".local/state/zkfy/integration.json"
BINDING = ".config/zkfy/knowledge.json"


def state(path):
    if path.is_symlink():
        return {"kind": "link", "target": os.readlink(path)}
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Refusing to replace a directory: {path}")
        return {"kind": "file", "data": base64.b64encode(path.read_bytes()).decode(), "mode": path.stat().st_mode & 0o777}
    return {"kind": "absent"}


def file_state(data, mode=0o600):
    return {"kind": "file", "data": base64.b64encode(data).decode(), "mode": mode}


def restore(path, desired):
    path.parent.mkdir(parents=True, exist_ok=True)
    if desired["kind"] == "absent":
        path.unlink(missing_ok=True)
    elif desired["kind"] == "link":
        with tempfile.TemporaryDirectory(dir=path.parent) as td:
            temp = Path(td) / "link"
            temp.symlink_to(desired["target"], target_is_directory=True)
            os.replace(temp, path)
    else:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            f.write(base64.b64decode(desired["data"]))
            os.fchmod(f.fileno(), desired["mode"])
        os.replace(f.name, path)


def skill_links(home):
    # Claude reads only ~/.claude/skills; Codex and Pi both read ~/.agents/skills;
    # Antigravity (CLI and IDE) reads neither, only ~/.gemini/config/skills.
    return {"claude": home / ".claude/skills/query", "agents": home / ".agents/skills/query",
            "agy": home / ".gemini/config/skills/query"}


def resolve_sources(home, vault, zkfy):
    """Explicit args win, then env, then the binding this machine already has."""
    vault = vault or os.environ.get("ZKFY_VAULT")
    zkfy = zkfy or os.environ.get("ZKFY_DIR")
    binding = home / BINDING
    if (not vault or not zkfy) and binding.is_file():
        bound = json.loads(binding.read_text())
        vault = vault or bound["vault"]
        zkfy = zkfy or str(Path(bound["tool"]).parents[1])
    if not vault or not zkfy:
        raise ValueError("vault/zkfy unknown: pass --vault/--zkfy or set ZKFY_VAULT and ZKFY_DIR")
    return Path(vault).expanduser().resolve(strict=True), Path(zkfy).expanduser().resolve(strict=True)


def desired_state(home, vault, zkfy, targets, python):
    if not (vault / "docs/knowledge/scope.json").is_file():
        raise ValueError("Vault scope must exist before installation")
    for name in ("scripts/knowledge.py", "scripts/knowledge-launcher.py", "skills/query/SKILL.md"):
        if not (zkfy / name).is_file():
            raise ValueError(f"Missing shared tooling in {zkfy}: {name}")
    binding = json.dumps({"version": 1, "vault": str(vault), "tool": str(zkfy / "scripts/knowledge.py"),
                          "python": python}, indent=2) + "\n"
    desired = {
        home / BINDING: file_state(binding.encode()),
        home / ".local/bin/vault-knowledge": {"kind": "link", "target": str(zkfy / "scripts/knowledge-launcher.py")},
    }
    links = skill_links(home)
    for target in targets:
        desired[links[target]] = {"kind": "link", "target": str(zkfy / "skills/query")}
    return desired


def install(home, vault=None, zkfy=None, targets=("claude", "agents", "agy"), apply=False, uninstall=False, python=sys.executable):
    home = home.expanduser().resolve()
    receipt_path = home / RECEIPT
    old = json.loads(receipt_path.read_text()) if receipt_path.exists() else {"version": 1, "files": {}}
    owned = {str(home / BINDING), str(home / ".local/bin/vault-knowledge"), *map(str, skill_links(home).values())}
    records, changes = {}, []
    for name in old["files"]:
        if name not in owned:
            print(f"Forget (no longer managed, left as is): {name}")
        else:
            records[name] = old["files"][name]
    if uninstall:
        for name, record in records.items():
            path, current = Path(name), state(Path(name))
            if current != record["after"]:
                raise ValueError(f"Installed artifact changed; refusing to discard edits: {path}")
            if current != record["before"]:
                changes.append((path, current, record["before"]))
        records = {}
    else:
        vault, zkfy = resolve_sources(home, vault, zkfy)
        for path, value in desired_state(home, vault, zkfy, targets, python).items():
            current, previous = state(path), records.get(str(path))
            expected = previous["after"] if previous else {"kind": "absent"}
            if current != expected and current != value:
                raise ValueError(f"Unmanaged/modified artifact; refusing to overwrite: {path}")
            records[str(path)] = {"before": previous["before"] if previous else current, "after": value}
            if current != value:
                changes.append((path, current, value))
    receipt = (file_state((json.dumps({"version": 1, "files": records}, indent=2, sort_keys=True) + "\n").encode())
               if records else {"kind": "absent"})
    prior_receipt = state(receipt_path)
    if prior_receipt != receipt:
        changes.append((receipt_path, prior_receipt, receipt))
    for path, _, _ in changes:
        print(("Apply: " if apply else "Would change: ") + str(path))
    if apply:
        done = []
        try:
            for path, before, after in changes:
                if state(path) != before:
                    raise ValueError(f"Concurrent edit detected: {path}")
                done.append((path, before))
                restore(path, after)
        except BaseException:
            for path, before in reversed(done):
                restore(path, before)
            raise
    print(f"knowledge: {len(changes)} changes")
    return len(changes)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", type=Path, default=Path.home())
    p.add_argument("--vault", type=Path)
    p.add_argument("--zkfy", type=Path)
    p.add_argument("--target", choices=("claude", "agents", "agy", "all"), default="all")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args()
    targets = ("claude", "agents", "agy") if args.target == "all" else (args.target,)
    try:
        install(args.home, args.vault, args.zkfy, targets, args.apply, args.uninstall)
    except (OSError, ValueError, KeyError) as e:
        print(f"knowledge: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
