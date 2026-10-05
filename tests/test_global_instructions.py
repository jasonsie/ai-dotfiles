from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "global_instructions", ROOT / "scripts/install-global-instructions.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class GlobalInstructionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="global instructions 空間 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.workspace = self.root / "workspace"
        self.source = self.workspace / "tools/instructions/AGENTS.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("# Shared preferences\n\nKeep project context local.\n")
        self.paths = {
            target: self.home / directory / filename
            for target, (directory, filename) in adapter.ENTRIES.items()
        }

    def install(self, targets=None, **kwargs):
        with redirect_stdout(io.StringIO()):
            return adapter.install(
                self.home,
                targets or tuple(adapter.ENTRIES),
                workspace=self.workspace,
                **kwargs,
            )

    def seed(self, target, content):
        path = self.paths[target]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def backups(self):
        return list(
            self.home.glob(".local/state/ai-cli-workspace/global-instructions/backup-*")
        )

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.install(), len(adapter.ENTRIES))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_same_source_and_live_updates_are_idempotent(self):
        self.assertEqual(self.install(apply=True), len(adapter.ENTRIES))
        original_times = {p: p.lstat().st_mtime_ns for p in self.paths.values()}
        self.source.write_text("# Updated shared preferences\n")
        for path in self.paths.values():
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.resolve(), self.source)
            self.assertEqual(path.read_text(), self.source.read_text())
        self.assertEqual(self.install(apply=True), 0)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(
            original_times, {p: p.lstat().st_mtime_ns for p in self.paths.values()}
        )

    def test_migrates_legacy_pointer_and_empty_file_with_backups(self):
        claude = self.seed("claude", f"@{self.workspace}/CLAUDE.md\n")
        claude.chmod(0o600)
        self.seed("gemini", "")
        before = {p: adapter.snapshot(p) for p in self.paths.values()}
        self.install(apply=True)
        backup = self.backups()[0]
        manifest = json.loads((backup / "manifest.json").read_text())
        self.assertEqual(adapter.snapshot(backup / "claude"), before[claude])
        self.assertEqual((backup / "gemini").read_bytes(), b"")
        self.assertIsNone(
            next(r for r in manifest if r["target"] == str(self.paths["codex"]))[
                "backup"
            ]
        )
        for record in manifest:
            adapter.restore_entry(
                Path(record["target"]),
                backup / record["backup"] if record["backup"] else None,
            )
        self.assertEqual(before, {p: adapter.snapshot(p) for p in self.paths.values()})

    def test_unknown_instructions_fail_before_any_write(self):
        self.seed("codex", "My personal rules\n")
        with self.assertRaisesRegex(ValueError, "Existing instructions"):
            self.install(apply=True)
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["gemini"].exists())
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.paths["codex"].read_text(), "My personal rules\n")

    def test_explicit_replacement_preserves_symlink_target(self):
        original = self.root / "old rules.md"
        original.write_text("Original rules\n")
        path = self.paths["gemini"]
        path.parent.mkdir(parents=True)
        path.symlink_to("../../old rules.md")
        with self.assertRaisesRegex(ValueError, "Existing instructions"):
            self.install(apply=True)
        self.install(apply=True, replace_existing=True)
        backup = self.backups()[0] / "gemini"
        self.assertTrue(backup.is_symlink())
        self.assertEqual(os.readlink(backup), "../../old rules.md")
        self.assertEqual(original.read_text(), "Original rules\n")
        adapter.restore_entry(path, backup)
        self.assertEqual(path.read_text(), original.read_text())

    def test_override_refused_even_after_installation(self):
        self.install(apply=True)
        override = self.paths["codex"].with_name("AGENTS.override.md")
        override.write_text("Override rules\n")
        with self.assertRaisesRegex(ValueError, "shadows shared instructions"):
            self.install(apply=True)
        self.assertEqual(override.read_text(), "Override rules\n")

    def test_pi_override_and_custom_agent_directory(self):
        custom = self.root / "custom pi agent"
        self.install(("pi",), apply=True, config_dirs={"pi": custom})
        self.assertEqual((custom / "AGENTS.md").resolve(), self.source)
        (custom / "AGENTS.override.md").write_text("override")
        with self.assertRaisesRegex(ValueError, "shadows shared instructions"):
            self.install(("pi",), apply=True, config_dirs={"pi": custom})

    def test_failure_rolls_back_all_changed_entries(self):
        self.seed("claude", f"@{self.workspace}/CLAUDE.md\n")
        self.seed("gemini", "")
        before = {p: adapter.snapshot(p) for p in self.paths.values()}
        original_replace = adapter.replace_link

        def failing(path, source):
            original_replace(path, source)
            if path == self.paths["gemini"]:
                raise OSError("injected write failure")

        with patch.object(adapter, "replace_link", failing):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                self.install(apply=True)
        self.assertEqual(before, {p: adapter.snapshot(p) for p in self.paths.values()})
        self.assertEqual(
            self.source.read_text(),
            "# Shared preferences\n\nKeep project context local.\n",
        )

    def test_single_target_and_custom_config_directory(self):
        custom = self.root / "custom codex home"
        self.install(("codex",), apply=True, config_dirs={"codex": custom})
        self.assertEqual((custom / "AGENTS.md").resolve(), self.source)
        for path in self.paths.values():
            self.assertFalse(path.exists())

    def test_nonfiles_and_invalid_source_are_refused(self):
        self.paths["claude"].mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "non-file"):
            self.install(apply=True, replace_existing=True)
        self.source.write_text("")
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            self.install(apply=True)
        self.source.write_text("a" * (32 * 1024))
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            self.install(apply=True)
        self.assertEqual(self.backups(), [])

    def test_source_cannot_be_replaced_through_a_directory_alias(self):
        alias = self.root / "source alias"
        alias.symlink_to(self.source.parent, target_is_directory=True)
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "destination is the shared source"):
            self.install(
                ("codex",),
                apply=True,
                replace_existing=True,
                config_dirs={"codex": alias},
            )
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.backups(), [])

    def test_non_directory_parent_refused_before_any_entry_changes(self):
        (self.home / ".codex").write_text("Not a directory\n")
        with self.assertRaisesRegex(ValueError, "parent is not a directory"):
            self.install(apply=True)
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["gemini"].exists())
        self.assertEqual(self.backups(), [])

    def test_settings_credentials_and_hooks_are_untouched(self):
        protected = []
        for target, (directory, _) in adapter.ENTRIES.items():
            for name in ("settings.json", "config.toml", "auth.json", "hooks.json"):
                path = self.home / directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"untouched fixture {target} {name}\n")
                protected.append(path)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected}
        self.install(apply=True)
        self.assertEqual(
            before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected}
        )

    def test_installer_instructions_only_and_target_selection(self):
        env = {**os.environ, "HOME": str(self.home)}
        for key in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR"):
            env.pop(key, None)
        command = [
            "bash",
            str(ROOT / "scripts/install.sh"),
            "--instructions-only",
            "--target=gemini",
        ]
        dry_run = subprocess.run(
            command + ["--dry-run"], env=env, capture_output=True, text=True
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        live = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(live.returncode, 0, live.stderr)
        self.assertTrue(self.paths["gemini"].is_symlink())
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["codex"].exists())
        self.assertFalse((self.home / ".gemini/settings.json").exists())
        self.assertFalse((self.home / ".ai-cli-workspace-path").exists())

    def test_full_install_dry_run_writes_nothing(self):
        env = {**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin"}
        for key in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR", "ZKFY_DIR", "ZKFY_VAULT"):
            env.pop(key, None)
        env["PYTHON"] = sys.executable
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/install.sh"), "--dry-run"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("knowledge: skipped", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
