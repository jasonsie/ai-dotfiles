from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import CLIS, ROOT, load, registry
import installer

adapter = load("install/instructions.py")


class GlobalInstructionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="global instructions 空間 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.workspace = self.root / "workspace"
        self.source = self.workspace / "config/global-agents.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("# Shared preferences\n\nKeep project context local.\n")
        self.paths = {cli: installer.path(self.home, cli, "instructions") for cli in CLIS}

    def install(self, clis=CLIS, **kwargs):
        with redirect_stdout(io.StringIO()):
            return adapter.install(self.home, clis, workspace=self.workspace, **kwargs)

    def uninstall(self, clis=CLIS, **kwargs):
        with redirect_stdout(io.StringIO()):
            return adapter.uninstall(self.home, clis, workspace=self.workspace, **kwargs)

    def seed(self, cli, content):
        path = self.paths[cli]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def backups(self):
        return list(self.home.glob(".local/state/ai-dotfiles/global-instructions/backup-*"))

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.install(), len(CLIS))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_same_source_and_live_updates_are_idempotent(self):
        self.assertEqual(self.install(apply=True), len(CLIS))
        original_times = {p: p.lstat().st_mtime_ns for p in self.paths.values()}
        self.source.write_text("# Updated shared preferences\n")
        for path in self.paths.values():
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.resolve(), self.source)
            self.assertEqual(path.read_text(), self.source.read_text())
        self.assertEqual(self.install(apply=True), 0)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(original_times, {p: p.lstat().st_mtime_ns for p in self.paths.values()})

    def test_from_a_linked_worktree_it_links_the_main_checkouts_copy(self):
        live = self.root / "main checkout"
        target = live / "config/global-agents.md"
        target.parent.mkdir(parents=True)
        target.write_text("# Shared preferences, as merged\n")
        self.assertEqual(self.install(apply=True, live=live), len(CLIS))
        self.assertEqual({os.readlink(p) for p in self.paths.values()}, {str(target)})
        self.assertEqual(self.install(live=live), 0)  # the main checkout's links are ours
        self.assertEqual(self.uninstall(live=live), len(CLIS))
        self.source.write_text("x" * 32 * 1024)  # the worktree's copy is the one checked
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            self.install(live=live)

    def test_replaces_an_empty_file_and_backs_it_up(self):
        empty = self.seed("agy", "")
        empty.chmod(0o600)
        self.install(apply=True)
        backup = self.backups()[0]
        manifest = json.loads((backup / "manifest.json").read_text())
        self.assertEqual(installer.state(backup / "agy"), ("file", b"", 0o600))
        self.assertIsNone(next(r for r in manifest if r["target"] == str(self.paths["codex"]))["backup"])
        self.assertEqual(empty.resolve(), self.source)

    def test_unknown_instructions_fail_before_any_write(self):
        self.seed("codex", "My personal rules\n")
        with self.assertRaisesRegex(ValueError, "Existing instructions"):
            self.install(apply=True)
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["agy"].exists())
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.paths["codex"].read_text(), "My personal rules\n")
        self.seed("codex", f"@{self.workspace}/CLAUDE.md\n")  # the retired pointer is no exception
        with self.assertRaisesRegex(ValueError, "Existing instructions"):
            self.install(apply=True)

    def test_explicit_replacement_preserves_symlink_target(self):
        original = self.root / "old rules.md"
        original.write_text("Original rules\n")
        path = self.paths["agy"]
        path.parent.mkdir(parents=True)
        path.symlink_to("../../old rules.md")
        with self.assertRaisesRegex(ValueError, "Existing instructions"):
            self.install(apply=True)
        self.install(apply=True, replace_existing=True)
        backup = self.backups()[0] / "agy"
        self.assertEqual(installer.state(backup), ("link", "../../old rules.md"))
        self.assertEqual(original.read_text(), "Original rules\n")
        installer.put(path, installer.state(backup))
        self.assertEqual(path.read_text(), original.read_text())

    def test_override_refused_even_after_installation(self):
        self.install(apply=True)
        for cli in ("codex", "pi"):
            override = self.paths[cli].with_name("AGENTS.override.md")
            override.write_text("Override rules\n")
            with self.assertRaisesRegex(ValueError, "shadows shared instructions"):
                self.install((cli,), apply=True)
            self.assertEqual(override.read_text(), "Override rules\n")

    def test_single_target(self):
        self.install(("codex",), apply=True)
        self.assertEqual(self.paths["codex"].resolve(), self.source)
        for cli in ("claude", "pi", "agy"):
            self.assertFalse(self.paths[cli].exists())

    def test_nonfiles_and_invalid_source_are_refused(self):
        self.paths["claude"].mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "non-file"):
            self.install(apply=True, replace_existing=True)
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, "Missing shared instructions"):
            self.install(apply=True)
        self.source.write_text("a" * (32 * 1024))
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            self.install(apply=True)
        self.assertEqual(self.backups(), [])

    def test_empty_source_is_linked(self):
        self.source.write_text("")
        self.install(apply=True)
        for path in self.paths.values():
            self.assertEqual(path.resolve(), self.source)

    def test_source_cannot_be_replaced_through_a_directory_alias(self):
        (self.home / ".codex").symlink_to(self.source.parent, target_is_directory=True)
        named_like_source = registry(self.root)
        data = json.loads(named_like_source.read_text())
        data["clis"]["codex"]["instructions"] = "~/.codex/global-agents.md"
        named_like_source.write_text(json.dumps(data))
        before = self.source.read_bytes()
        with patch.object(installer, "REGISTRY", named_like_source), \
                self.assertRaisesRegex(ValueError, "destination is the shared source"):
            self.install(("codex",), apply=True, replace_existing=True)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.backups(), [])

    def test_non_directory_parent_refused_before_any_entry_changes(self):
        (self.home / ".codex").write_text("Not a directory\n")
        with self.assertRaisesRegex(ValueError, "parent is not a directory"):
            self.install(apply=True)
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["agy"].exists())
        self.assertEqual(self.backups(), [])

    def test_settings_credentials_and_hooks_are_untouched(self):
        protected = []
        for cli, path in self.paths.items():
            for name in ("settings.json", "config.toml", "auth.json", "hooks.json"):
                fixture = path.parent / name
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.write_text(f"untouched fixture {cli} {name}\n")
                protected.append(fixture)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected}
        self.install(apply=True)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected})

    def test_installer_instructions_only_and_target_selection(self):
        env = {**os.environ, "HOME": str(self.home)}
        command = ["bash", str(ROOT / "scripts/install.sh"), "--instructions-only", "--target=agy"]
        preview = subprocess.run(command + ["--dry-run"], env=env, capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        live = subprocess.run(command, env=env, capture_output=True, text=True)  # writes by default
        self.assertEqual(live.returncode, 0, live.stderr)
        self.assertTrue(self.paths["agy"].is_symlink())
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["codex"].exists())
        self.assertFalse((self.home / ".gemini/settings.json").exists())

    def test_full_install_dry_run_writes_nothing(self):
        env = {**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin", "PYTHON": sys.executable}
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/install.sh"), "--dry-run"], env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preview only", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_uninstall_restores_original_file(self):
        path = self.seed("codex", "My rules\n")
        path.chmod(0o600)
        before = installer.state(path)
        self.install(("codex",), apply=True, replace_existing=True)
        self.assertEqual(self.uninstall(("codex",), apply=True), 1)
        self.assertEqual(installer.state(path), before)
        self.assertEqual(self.uninstall(apply=True), 0)  # nothing of ours left

    def test_uninstall_earliest_manifest_wins_across_cycles(self):
        path = self.seed("codex", "First original\n")
        self.install(("codex",), apply=True, replace_existing=True)
        self.uninstall(("codex",), apply=True)
        path.write_text("Second original\n")
        self.install(("codex",), apply=True, replace_existing=True)
        self.assertEqual(len(self.backups()), 3)
        # mtimes in creation order are not guaranteed to differ; set them
        install1, uninstall1, install2 = sorted(
            self.backups(), key=lambda b: (b / "manifest.json").stat().st_mtime_ns
        )
        for i, b in enumerate((install1, uninstall1, install2)):
            os.utime(b / "manifest.json", (1000 + i, 1000 + i))
        self.uninstall(("codex",), apply=True)
        self.assertEqual(path.read_text(), "First original\n")

    def test_uninstall_from_absent_leaves_path_absent(self):
        self.install(apply=True)
        self.assertEqual(self.uninstall(apply=True), len(CLIS))
        for path in self.paths.values():
            self.assertFalse(path.is_symlink() or path.exists())
        self.assertEqual(self.uninstall(apply=True), 0)

    def test_uninstall_leaves_foreign_entries(self):
        foreign = self.seed("codex", "Mine\n")
        elsewhere = self.root / "elsewhere.md"
        elsewhere.write_text("x")
        self.paths["agy"].parent.mkdir(parents=True)
        self.paths["agy"].symlink_to(elsewhere)
        self.assertEqual(self.uninstall(apply=True), 0)
        self.assertEqual(foreign.read_text(), "Mine\n")
        self.assertEqual(self.paths["agy"].resolve(), elsewhere)
        self.assertEqual(self.backups(), [])

    def test_uninstall_dry_run_writes_nothing(self):
        path = self.seed("codex", "Mine\n")
        self.install(("codex",), apply=True, replace_existing=True)
        before = (self.backups(), os.readlink(path))
        self.assertEqual(self.uninstall(("codex",)), 1)
        self.assertEqual((self.backups(), os.readlink(path)), before)
        self.assertEqual(len(self.backups()), 1)

    def test_uninstall_skips_original_that_was_our_own_old_link(self):
        path = self.seed("codex", "Real original\n")
        self.install(("codex",), apply=True, replace_existing=True)
        # an older install from a moved checkout, recorded earliest
        old = self.home / ".local/state/ai-dotfiles/global-instructions/backup-old"
        old.mkdir()
        (old / "codex").symlink_to("/old/checkout/tools/instructions/AGENTS.md")
        (old / "manifest.json").write_text(
            json.dumps([{"target": str(path), "original_kind": "link", "backup": "codex"}])
        )
        os.utime(old / "manifest.json", (1, 1))
        for b in self.backups():
            if b != old:
                os.utime(b / "manifest.json", (2, 2))
        self.uninstall(("codex",), apply=True)
        self.assertEqual(path.read_text(), "Real original\n")

    def test_a_link_to_the_source_before_config_is_ours(self):
        old = "/old/checkout/tools/instructions/AGENTS.md"  # where the source lived before config/
        path = self.paths["codex"]
        path.parent.mkdir(parents=True)
        path.symlink_to(old)
        self.assertEqual(self.uninstall(("codex",)), 1)  # uninstall would remove it
        self.assertEqual(self.install(("codex",), apply=True), 1)  # no --replace-existing needed
        self.assertEqual(path.resolve(), self.source)
        self.uninstall(("codex",), apply=True)
        self.assertFalse(path.is_symlink() or path.exists())  # the old link is not an original

    def test_a_cli_switched_off_is_unlinked_and_its_original_restored(self):
        path = self.seed("agy", "Mine\n")
        self.install(apply=True, replace_existing=True)
        run = lambda: adapter.run(self.home, "all", True, False, False, workspace=self.workspace)  # noqa: E731
        with patch.object(installer, "REGISTRY", registry(self.root, agy=False)), redirect_stdout(io.StringIO()):
            self.assertEqual(run(), 1)
            self.assertEqual(path.read_text(), "Mine\n")
            self.assertEqual(run(), 0)
        self.assertEqual(self.paths["claude"].resolve(), self.source)

    def test_uninstall_skips_stale_originals(self):
        live = self.root / "live.md"
        live.write_text("x")
        self.seed("claude", f"@{self.root}/gone/CLAUDE.md\n")  # import of a file now gone
        self.seed("agy", "")
        self.seed("codex", f"@{live}\n")  # a live import is the user's own: restored
        self.seed("pi", "\n<!-- zkfy-knowledge:start -->\n# Old\n<!-- zkfy-knowledge:end -->\n")
        self.install(apply=True, replace_existing=True)
        self.uninstall(apply=True)
        self.assertFalse(self.paths["claude"].exists())
        self.assertFalse(self.paths["agy"].exists())
        self.assertFalse(self.paths["pi"].exists())
        self.assertEqual(self.paths["codex"].read_text(), f"@{live}\n")

    def test_uninstall_restores_user_text_around_a_tool_block(self):
        text = "My rule\n<!-- zkfy-knowledge:start -->\nx\n<!-- zkfy-knowledge:end -->\n"
        path = self.seed("pi", text)
        self.install(("pi",), apply=True, replace_existing=True)
        self.uninstall(("pi",), apply=True)
        self.assertEqual(path.read_text(), text)


if __name__ == "__main__":
    unittest.main()
