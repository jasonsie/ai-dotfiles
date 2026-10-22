import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from support import load

a = load("install/knowledge.py")


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge adapter 空間 ")
        self.root = Path(self.temp.name).resolve()
        self.home, self.vault, self.zkfy = [self.root / x for x in ("home", "vault", "zkfy")]
        self.home.mkdir()
        for p in (self.vault / "docs/knowledge/scope.json", self.zkfy / "scripts/knowledge.py",
                  self.zkfy / "scripts/knowledge-launcher.py", self.zkfy / "skills/query/SKILL.md"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture")

    def tearDown(self):
        self.temp.cleanup()

    def install(self, **kw):
        kw.setdefault("vault", self.vault)
        kw.setdefault("zkfy", self.zkfy)
        return a.install(self.home, python="/usr/bin/python3", **kw)

    def snapshot(self):
        return {p: (os.readlink(p) if p.is_symlink() else p.read_bytes())
                for p in self.home.rglob("*") if p.is_symlink() or p.is_file()}

    def test_dry_run_idempotency_and_exact_reversal(self):
        agents = self.home / ".pi/agent/AGENTS.md"
        agents.parent.mkdir(parents=True)
        agents.symlink_to(self.root / "shared-AGENTS.md")
        before = self.snapshot()
        self.assertEqual(self.install(), 3)  # binding, launcher, receipt
        self.assertEqual(before, self.snapshot())
        self.install(apply=True)
        self.assertEqual(self.install(), 0)
        self.assertTrue((self.home / a.LAUNCHER).is_symlink())
        self.assertEqual(json.loads((self.home / a.BINDING).read_text())["vault"], str(self.vault))
        self.assertTrue(agents.is_symlink())  # instruction entries are never touched
        self.install(apply=True, uninstall=True)
        self.assertFalse((self.home / a.LAUNCHER).exists())
        self.assertFalse((self.home / a.RECEIPT).exists())
        self.assertTrue(agents.is_symlink())

    def test_existing_binding_supplies_paths(self):
        self.install(apply=True)
        with patch.dict(os.environ, {"ZKFY_VAULT": "", "ZKFY_DIR": ""}):
            self.assertEqual(a.install(self.home, python="/usr/bin/python3"), 0)

    def test_env_supplies_paths(self):
        with patch.dict(os.environ, {"ZKFY_VAULT": str(self.vault), "ZKFY_DIR": str(self.zkfy)}):
            self.assertEqual(a.install(self.home, python="/usr/bin/python3"), 3)

    def test_missing_paths_fail_clearly(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            env.pop("ZKFY_VAULT", None)
            env.pop("ZKFY_DIR", None)
            with self.assertRaisesRegex(ValueError, "ZKFY_DIR"):
                a.install(self.home)

    def test_missing_zkfy_tooling_fails_before_any_write(self):
        (self.zkfy / "skills/query/SKILL.md").unlink()
        with self.assertRaisesRegex(ValueError, "skills/query"):
            self.install(apply=True)
        self.assertFalse((self.home / a.BINDING).exists())

    def test_entries_no_longer_managed_are_forgotten_not_touched(self):
        legacy = self.home / ".claude/rules/vault-knowledge.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("now user-owned")
        query = self.home / ".claude/skills/query"  # linked by the skills step now
        query.parent.mkdir(parents=True)
        query.symlink_to(self.zkfy / "skills/query")
        receipt = self.home / a.RECEIPT
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"version": 1, "files": {
            str(legacy): {"before": {"kind": "absent"}, "after": {"kind": "file", "data": "", "mode": 420}},
            str(query): {"before": {"kind": "absent"}, "after": {"kind": "link", "target": str(self.zkfy / "skills/query")}}}}))
        self.install(apply=True)
        self.assertNotIn(str(query), json.loads(receipt.read_text())["files"])
        self.install(apply=True, uninstall=True)
        self.assertEqual(legacy.read_text(), "now user-owned")
        self.assertTrue(query.is_symlink())

    def test_refuses_collisions_before_any_write(self):
        launcher = self.home / a.LAUNCHER
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\n# mine\n")
        with self.assertRaisesRegex(ValueError, "refusing"):
            self.install(apply=True)
        self.assertFalse((self.home / a.BINDING).exists())


if __name__ == "__main__":
    unittest.main()
