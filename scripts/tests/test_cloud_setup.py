"""scripts/cloud/setup.sh, run by a cloud environment's setup script, against a sandbox: a copy of
the repo, a temporary home, plugin and command folders, and a git that only fakes clones."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ROOT

ENVIRONMENT = ROOT / 'scripts/cloud/environment.sh'
REPORT_PATH = '/opt/ai-dotfiles-setup.txt'  # where both scripts say the report goes on the VM

# A clone makes the folder; zkfy's copy carries a cloud/setup.sh that records the pins it was given.
FAKE_GIT = r'''#!/bin/bash
[ "$1" = clone ] || exit 1
[ -n "$FAIL_CLONES" ] && exit 128
dest="${@: -1}"
url="${@: -2:1}"
mkdir -p "$dest"
if [ "${url##*/}" = zkfy ]; then
  mkdir -p "$dest/cloud"
  printf '#!/bin/bash\necho "ZKFY_REF=$ZKFY_REF WEB_CLIPPER_REF=$WEB_CLIPPER_REF" >> "$SEEN"\n' > "$dest/cloud/setup.sh"
fi
'''


def pins():
    """{name: (source, release tag)} of the plugins config/plugins.json gives Claude."""
    plugins = json.loads((ROOT / 'config/plugins.json').read_text())['plugins']
    return {name: (p['source'], f"{name}--v{p['version']}") for name, p in plugins.items() if 'claude' in p['targets']}


class CloudSetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='cloud setup '))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.checkout = self.temp / 'ai-dotfiles'
        for folder in ('scripts', 'lib', 'config', 'skills'):
            shutil.copytree(ROOT / folder, self.checkout / folder, ignore=shutil.ignore_patterns('__pycache__'))
        self.home, self.plugins, self.bin = self.temp / 'root', self.temp / 'ai-plugins', self.temp / 'bin'
        self.home.mkdir()
        stubs = self.temp / 'stubs'
        stubs.mkdir()
        (stubs / 'git').write_text(FAKE_GIT)
        (stubs / 'git').chmod(0o755)
        self.report, self.seen = self.temp / 'setup.txt', self.temp / 'seen.txt'
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': f'{stubs}:/usr/bin:/bin', 'PYTHON': sys.executable,
                    'AI_PLUGINS_DIR': str(self.plugins), 'AI_DOTFILES_BIN': str(self.bin),
                    'AI_DOTFILES_REPORT': str(self.report), 'SEEN': str(self.seen)}

    def setup(self, **extra):
        run = subprocess.run(['bash', str(self.checkout / 'scripts/cloud/setup.sh')], env={**self.env, **extra},
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return self.report.read_text()

    def test_it_lays_out_the_install_the_command_and_the_plugins_at_their_pins(self):
        report = self.setup()
        self.assertIn('ok   install', report)
        self.assertTrue((self.home / '.claude/CLAUDE.md').is_symlink())
        self.assertEqual(Path(os.readlink(self.bin / 'ai-dotfiles')), self.checkout / 'scripts/ai-dotfiles')
        for name, (source, tag) in pins().items():
            with self.subTest(name):
                self.assertIn(f'ok   clone      {source}@{tag}', report)
                self.assertTrue((self.plugins / name).is_dir())
        seen = f"ZKFY_REF={pins()['zkfy'][1]} WEB_CLIPPER_REF={pins()['web-clipper'][1]}\n"
        self.assertEqual(self.seen.read_text(), seen, "zkfy's setup gets its own pin and web-clipper's")
        self.assertIn('ok   plugin     zkfy/cloud/setup.sh', report)
        dirs = ':'.join(str(self.plugins / name) for name in pins())
        self.assertIn(f'CLAUDE_CODE_PLUGIN_DIRS={dirs}', report)

    def test_a_failing_step_is_reported_and_never_fails_the_session(self):
        report = self.setup(FAIL_CLONES='1')
        self.assertIn('ok   install', report)
        for source, tag in pins().values():
            self.assertIn(f'FAIL clone      {source}@{tag}', report)
        self.assertFalse(self.seen.exists(), 'no plugin setup without its clone')

    def test_the_environment_script_clones_this_repo_and_runs_the_setup(self):
        text = ENVIRONMENT.read_text()
        self.assertLess(len(text.encode()), 64 * 1024, 'the environment dialog takes up to 64 KB')
        self.assertIn('git clone --quiet --depth 1 https://github.com/jasonsie/ai-dotfiles /opt/ai-dotfiles', text)
        self.assertIn('bash /opt/ai-dotfiles/scripts/cloud/setup.sh', text)
        self.assertEqual(text.rstrip().splitlines()[-1], 'exit 0', 'a setup script that fails stops the session')
        self.assertIn(REPORT_PATH, text)
        self.assertIn(REPORT_PATH, (ROOT / 'scripts/cloud/setup.sh').read_text())


if __name__ == '__main__':
    unittest.main()
