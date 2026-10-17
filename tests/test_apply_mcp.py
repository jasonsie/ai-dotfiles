import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mcp', ROOT / 'scripts/apply-mcp.py')
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)

SERVER = {'name': 'docs', 'command': 'npx', 'args': ['-y', 'pkg'], 'description': 'Docs lookup',
          'targets': ['claude', 'codex', 'pi', 'agy']}


class ApplyMcpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def agy_config(self, text=''):
        path = self.home / mcp.AGY_CONFIG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_repo_servers_have_no_secrets(self):
        servers = json.loads(mcp.SERVERS.read_text())['servers']
        self.assertTrue(servers)
        for server in servers:
            self.assertNotIn('env', server)
            self.assertLessEqual(set(server['targets']), set(mcp.CLIS))

    def test_only_missing_servers_are_added(self):
        (self.home / '.claude.json').write_text(json.dumps({'mcpServers': {'docs': {}}}))
        (self.home / '.codex').mkdir()
        (self.home / '.codex/config.toml').write_text('[mcp_servers.other]\ncommand = "x"\n')
        commands, files = mcp.plan(self.home, mcp.CLIS, [SERVER], which=lambda _: True)
        self.assertEqual(commands, [['codex', 'mcp', 'add', 'docs', '--', 'npx', '-y', 'pkg'],
                                    ['pi', 'mcp', 'add', 'docs', '--description', 'Docs lookup', '--', 'npx', '-y', 'pkg']])
        self.assertEqual(files, [])  # Antigravity is not set up in this home

    def test_claude_registers_at_user_scope(self):
        commands, _ = mcp.plan(self.home, ('claude',), [SERVER], which=lambda _: True)
        self.assertEqual(commands, [['claude', 'mcp', 'add', '-s', 'user', 'docs', '--', 'npx', '-y', 'pkg']])

    def test_agy_merge_keeps_other_content_and_is_idempotent(self):
        path = self.agy_config(json.dumps({'mcpServers': {'mine': {'command': 'x'}}, 'other': 1}))
        _, files = mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True)
        self.assertEqual([f[0] for f in files], [path])
        backup = mcp.write_files(self.home, files)
        data = json.loads(path.read_text())
        self.assertEqual(data['mcpServers']['docs'], {'command': 'npx', 'args': ['-y', 'pkg']})
        self.assertEqual(data['mcpServers']['mine'], {'command': 'x'})
        self.assertEqual(data['other'], 1)
        self.assertTrue((backup / mcp.AGY_CONFIG).is_file())
        self.assertEqual(mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True), ([], []))

    def test_agy_empty_file_and_symlink(self):
        path = self.agy_config('')
        _, files = mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True)
        mcp.write_files(self.home, files)
        self.assertIn('docs', json.loads(path.read_text())['mcpServers'])
        path.unlink()
        target = self.home / 'shared.json'
        target.write_text('{}')
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True)

    def test_targets_and_missing_cli_respected(self):
        server = {**SERVER, 'targets': ['codex']}
        self.assertEqual(mcp.plan(self.home, mcp.CLIS, [server], which=lambda cli: cli != 'codex'), ([], []))


if __name__ == '__main__':
    unittest.main()
