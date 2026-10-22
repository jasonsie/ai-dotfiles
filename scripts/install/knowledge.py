#!/usr/bin/env python3
"""Bind the zkfy vault tooling; writes unless --dry-run.

Installs two artifacts: the launcher binding (~/.config/zkfy/knowledge.json) and the
`vault-knowledge` launcher link. zkfy's `query` skill is linked by skills.py,
with the other skills; retrieval guidance lives in that skill, and instruction files are
never touched here. A receipt records prior state so --uninstall restores it exactly.

Paths come from --vault/--zkfy, then ZKFY_VAULT/ZKFY_DIR, then the existing binding.
"""
import base64
import json
import os
from pathlib import Path
import sys

import installer

RECEIPT = ".local/state/zkfy/integration.json"
BINDING = installer.ZKFY_BINDING
LAUNCHER = ".local/bin/vault-knowledge"


def encode(state):
    """A path state as the receipt stores it."""
    if state[0] == "link":
        return {"kind": "link", "target": state[1]}
    if state[0] == "file":
        return {"kind": "file", "data": base64.b64encode(state[1]).decode(), "mode": state[2]}
    return {"kind": state[0]}


def decode(record):
    if record["kind"] == "link":
        return ("link", record["target"])
    if record["kind"] == "file":
        return ("file", base64.b64decode(record["data"]), record["mode"])
    return (record["kind"],)


def resolve_sources(home, vault, zkfy):
    """Explicit args win, then env, then the binding this machine already has."""
    vault = vault or os.environ.get("ZKFY_VAULT")
    binding = home / BINDING
    if not vault and binding.is_file():
        vault = json.loads(binding.read_text())["vault"]
    zkfy = zkfy or installer.zkfy_dir(home)
    if not vault or not zkfy:
        raise ValueError("vault/zkfy unknown: pass --vault/--zkfy or set ZKFY_VAULT and ZKFY_DIR")
    return Path(vault).expanduser().resolve(strict=True), Path(zkfy).expanduser().resolve(strict=True)


def desired_state(home, vault, zkfy, python):
    if not (vault / "docs/knowledge/scope.json").is_file():
        raise ValueError("Vault scope must exist before installation")
    for name in ("scripts/knowledge.py", "scripts/knowledge-launcher.py", "skills/query/SKILL.md"):
        if not (zkfy / name).is_file():
            raise ValueError(f"Missing shared tooling in {zkfy}: {name}")
    binding = json.dumps({"version": 1, "vault": str(vault), "tool": str(zkfy / "scripts/knowledge.py"),
                          "python": python}, indent=2) + "\n"
    return {
        home / BINDING: ("file", binding.encode(), 0o600),
        home / LAUNCHER: ("link", str(zkfy / "scripts/knowledge-launcher.py")),
    }


def install(home, vault=None, zkfy=None, apply=False, uninstall=False, python=sys.executable):
    home = home.expanduser().resolve()
    receipt_path = home / RECEIPT
    old = json.loads(receipt_path.read_text()) if receipt_path.exists() else {"version": 1, "files": {}}
    owned = {str(home / BINDING), str(home / LAUNCHER)}
    records, changes = {}, []
    for name in old["files"]:
        if name not in owned:
            print(f"Forget (no longer managed, left as is): {name}")
        else:
            records[name] = old["files"][name]
    if uninstall:
        for name, record in records.items():
            path, current = Path(name), installer.state(Path(name))
            if current != decode(record["after"]):
                raise ValueError(f"Installed artifact changed; refusing to discard edits: {path}")
            if current != decode(record["before"]):
                changes.append((path, current, decode(record["before"])))
        records = {}
    else:
        vault, zkfy = resolve_sources(home, vault, zkfy)
        for path, value in desired_state(home, vault, zkfy, python).items():
            current, previous = installer.state(path), records.get(str(path))
            expected = decode(previous["after"]) if previous else ("absent",)
            if current != expected and current != value:
                raise ValueError(f"Unmanaged/modified artifact; refusing to overwrite: {path}")
            records[str(path)] = {"before": previous["before"] if previous else encode(current), "after": encode(value)}
            if current != value:
                changes.append((path, current, value))
    receipt = installer.receipt({"version": 1, "files": records}) if records else ("absent",)
    if installer.state(receipt_path) != receipt:
        changes.append((receipt_path, installer.state(receipt_path), receipt))
    installer.show(changes, apply)
    if apply and changes:
        installer.apply(home, changes)
    return len(changes)


def main():
    parser = installer.parser(__doc__, cli_target=False)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--zkfy", type=Path)
    args = parser.parse_args()
    return installer.finish("knowledge", lambda: install(
        args.home, args.vault, args.zkfy, not args.dry_run, args.uninstall))


if __name__ == "__main__":
    sys.exit(main())
