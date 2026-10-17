import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('report', ROOT / 'scripts/report-upstream.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

DIFF = '''diff --git a/upstream/docs/codex/docs/config.md b/upstream/docs/codex/docs/config.md
--- a/upstream/docs/codex/docs/config.md
+++ b/upstream/docs/codex/docs/config.md
@@ -3 +3,2 @@
-sandbox_mode = "workspace-write"
+sandbox_mode = "workspace-write-v2"
+The model picks a sandbox for you.
diff --git a/upstream/docs/claude/skills.md b/upstream/docs/claude/skills.md
--- a/upstream/docs/claude/skills.md
+++ b/upstream/docs/claude/skills.md
@@ -9,0 +10 @@
+Claude Code now also reads `~/.agents/skills`.
diff --git a/upstream/docs/pi/themes.md b/upstream/docs/pi/themes.md
--- a/upstream/docs/pi/themes.md
+++ b/upstream/docs/pi/themes.md
@@ -1 +1 @@
-Dark theme
+Dark themes
'''


class ReportUpstreamTest(unittest.TestCase):
    def test_parse_diff_keeps_changed_lines_per_file(self):
        files = report.parse_diff(DIFF)
        added, removed = files['upstream/docs/codex/docs/config.md']
        self.assertEqual(removed, ['sandbox_mode = "workspace-write"'])
        self.assertEqual(len(added), 2)
        self.assertEqual(len(files), 3)

    def test_setup_section_flags_only_watched_names(self):
        keys = ['sandbox_mode', 'model', 'effortLevel']
        lines = report.section_setup(report.parse_diff(DIFF), keys)
        self.assertEqual(len(lines), 2)
        self.assertIn('`sandbox_mode`', lines[1])
        self.assertNotIn('`model`', lines[1])  # "The model picks…" is prose, not the key
        self.assertIn('`.agents/skills`', lines[0])

    def test_page_counts_per_tool(self):
        counts = report.page_counts('M\tupstream/docs/codex/a.md\nA\tupstream/docs/pi/b.md\n'
                                    'D\tupstream/docs/pi/c.md\nR100\tupstream/docs/pi/d.md\tupstream/docs/pi/e.md\n')
        self.assertEqual(counts, {'codex': {'A': 0, 'D': 0, 'M': 1}, 'pi': {'A': 1, 'D': 1, 'M': 1}})

    def test_new_skills_ignore_a_first_snapshot(self):
        before = {'mattpocock/skills': ['grilling']}
        after = {'mattpocock/skills': ['grilling', 'tdd'], 'anthropics/skills': ['pdf']}
        self.assertEqual(report.new_skills(before, after), {'mattpocock/skills': ['tdd']})

    def test_managed_keys_come_from_both_groups(self):
        keys = report.managed_keys({'version': 2, 'codex': {'enforce': {'sandbox_mode': 'x'}, 'default': {'model': 'm'}}})
        self.assertEqual(keys, ['model', 'sandbox_mode'])


if __name__ == '__main__':
    unittest.main()
