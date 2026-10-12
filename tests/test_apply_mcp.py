import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mcp', ROOT / 'scripts/apply-mcp.py')
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)

SERVER = {'name': 'docs', 'command': 'npx', 'args': ['-y', 'pkg'], 'targets': ['claude', 'codex', 'gemini']}


class ApplyMcpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

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
        commands = mcp.plan(self.home, mcp.CLIS, [SERVER], which=lambda _: True)
        self.assertEqual([c[0] for c in commands], ['codex', 'gemini'])
        self.assertEqual(commands[0], ['codex', 'mcp', 'add', 'docs', '--', 'npx', '-y', 'pkg'])
        self.assertEqual(commands[1][:5], ['gemini', 'mcp', 'add', '-s', 'user'])

    def test_targets_and_missing_cli_respected(self):
        server = {**SERVER, 'targets': ['gemini']}
        commands = mcp.plan(self.home, mcp.CLIS, [server], which=lambda cli: cli != 'gemini')
        self.assertEqual(commands, [])


if __name__ == '__main__':
    unittest.main()
