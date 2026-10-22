import json
from pathlib import Path
import tempfile
import unittest

from support import CLIS, load, where
import installer

mcp = load('install/mcp.py')

SERVER = {'name': 'docs', 'command': 'npx', 'args': ['-y', 'pkg'], 'description': 'Docs lookup',
          'targets': ['claude', 'codex', 'pi', 'agy']}
AGY_CONFIG = where('agy', 'mcp')


class ApplyMcpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def agy_config(self, text=''):
        path = self.home / AGY_CONFIG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_repo_servers_have_no_secrets(self):
        servers = json.loads(mcp.SERVERS.read_text())['servers']
        self.assertTrue(servers)
        for server in servers:
            self.assertNotIn('env', server)
            self.assertLessEqual(set(server['targets']), set(CLIS))

    def test_only_missing_servers_are_added(self):
        (self.home / '.claude.json').write_text(json.dumps({'mcpServers': {'docs': {}}}))
        (self.home / '.codex').mkdir()
        (self.home / '.codex/config.toml').write_text('[mcp_servers.other]\ncommand = "x"\n')
        commands, files = mcp.plan(self.home, CLIS, [SERVER], which=lambda _: True)
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
        backup = installer.apply(self.home, files, backup='mcp')
        data = json.loads(path.read_text())
        self.assertEqual(data['mcpServers']['docs'], {'command': 'npx', 'args': ['-y', 'pkg']})
        self.assertEqual(data['mcpServers']['mine'], {'command': 'x'})
        self.assertEqual(data['other'], 1)
        self.assertTrue((backup / AGY_CONFIG).is_file())
        self.assertEqual(mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True), ([], []))

    def test_agy_empty_file_and_symlink(self):
        path = self.agy_config('')
        _, files = mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True)
        installer.apply(self.home, files)
        self.assertIn('docs', json.loads(path.read_text())['mcpServers'])
        path.unlink()
        target = self.home / 'shared.json'
        target.write_text('{}')
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            mcp.plan(self.home, ('agy',), [SERVER], which=lambda _: True)

    def test_targets_and_missing_cli_respected(self):
        server = {**SERVER, 'targets': ['codex']}
        self.assertEqual(mcp.plan(self.home, CLIS, [server], which=lambda cli: cli != 'codex'), ([], []))


if __name__ == '__main__':
    unittest.main()
