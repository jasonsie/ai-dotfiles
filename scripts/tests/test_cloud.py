"""A cloud session reads only the clone: this repo's .claude/settings.json gives it the global
rules, the ai-dotfiles command and the commit gate (scripts/cloud_session.py)."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT, load

hooks_step = load('install/hooks.py')

SESSION = ROOT / 'scripts/cloud_session.py'
SETTINGS = ROOT / '.claude/settings.json'
RULES = (ROOT / 'config/global-agents.md').read_text().strip()
GATE, TAIL = '[ "$CLAUDE_CODE_REMOTE" = true ] && ', ' || true'
SCRIPT = re.compile(r'"\$CLAUDE_PROJECT_DIR/([^"]+)"')
STARTUP = json.dumps({'hook_event_name': 'SessionStart', 'source': 'startup'})


def hooks():
    """{event: [(matcher, handler)]} in the committed .claude/settings.json."""
    data = json.loads(SETTINGS.read_text())['hooks']
    return {event: [(entry.get('matcher'), hook) for entry in entries for hook in entry['hooks']]
            for event, entries in data.items()}


class Sandbox(unittest.TestCase):
    """A temporary project folder (a clone, as a cloud session sees it) with a HOME and a git
    config of its own; its config/, scripts/ and skills/ are links to this repo's."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.project = self.temp / 'clone'
        self.project.mkdir()
        for name in ('config', 'scripts', 'skills'):
            (self.project / name).symlink_to(ROOT / name)

    def env(self, remote, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_REMOTE', 'CLAUDE_ENV_FILE')}
        env.update(HOME=str(self.temp), GIT_CONFIG_GLOBAL=os.devnull, CLAUDE_PROJECT_DIR=str(self.project),
                   **extra)
        if remote:
            env['CLAUDE_CODE_REMOTE'] = 'true'
        return env

    def run_sh(self, command, remote, stdin, **extra):
        """A command as Claude Code runs a hook: through sh, the event on stdin. (exit code, stdout)."""
        run = subprocess.run(['sh', '-c', command], input=stdin, env=self.env(remote, **extra),
                             capture_output=True, text=True)
        return run.returncode, run.stdout

    def start(self, remote, **extra):
        """The SessionStart hook's command, as .claude/settings.json gives it."""
        (_, handler), = hooks()['SessionStart']
        return self.run_sh(handler['command'], remote, STARTUP, **extra)

    def reply(self, out):
        hook = json.loads(out)['hookSpecificOutput']
        self.assertEqual(hook['hookEventName'], 'SessionStart')
        return hook


class SessionStartTest(Sandbox):
    """In a cloud session, start hands Claude the global rules and puts scripts/ on PATH."""

    def test_a_cloud_session_gets_the_global_rules(self):
        code, out = self.start(True, CLAUDE_ENV_FILE=str(self.temp / 'env.sh'))
        self.assertEqual(code, 0)
        self.assertIn(RULES, self.reply(out)['additionalContext'])

    def test_a_cloud_session_gets_scripts_on_path_once(self):
        env_file = self.temp / 'env.sh'
        self.start(True, CLAUDE_ENV_FILE=str(env_file))
        self.start(True, CLAUDE_ENV_FILE=str(env_file))  # resume, clear, compact: the line stays single
        self.assertEqual(len(env_file.read_text().splitlines()), 1)
        found = subprocess.run(['sh', '-c', f'. "{env_file}" && command -v ai-dotfiles'],
                               capture_output=True, text=True)
        self.assertEqual(found.stdout.strip(), str(self.project / 'scripts/ai-dotfiles'))

    def test_a_mac_session_gets_nothing(self):
        env_file = self.temp / 'env.sh'
        self.assertEqual(self.start(False, CLAUDE_ENV_FILE=str(env_file)), (0, ''))
        self.assertFalse(env_file.exists())

    def test_a_path_it_cannot_set_is_said_and_the_rules_still_come(self):
        for extra in ({}, {'CLAUDE_ENV_FILE': str(self.temp / 'no-such-folder' / 'env.sh')}):
            with self.subTest(extra):
                code, out = self.start(True, **extra)
                self.assertEqual(code, 0)
                context = self.reply(out)['additionalContext']
                self.assertIn(RULES, context)
                self.assertIn('scripts/ is not on PATH', context)


class ProjectSettingsTest(Sandbox):
    """.claude/settings.json runs its hooks in a cloud session only: a Mac runs the user-level ones."""

    def test_git_tracks_it(self):
        ignored = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '-q', str(SETTINGS)])
        self.assertEqual(ignored.returncode, 1, '.gitignore must not hide .claude/settings.json')

    def test_every_hook_is_gated_and_names_a_script_here(self):
        for event, entries in hooks().items():
            for _, handler in entries:
                command = handler['command']
                with self.subTest(event=event, command=command):
                    self.assertTrue(command.startswith(GATE), 'runs on a Mac too, beside the user-level hook')
                    self.assertTrue(command.endswith(TAIL), 'a failing hook must not fail the call')
                    names = SCRIPT.findall(command)
                    self.assertTrue(names)
                    for name in names:
                        self.assertTrue((ROOT / name).is_file(), name)

    def test_session_start_runs_on_every_start(self):
        (matcher, handler), = hooks()['SessionStart']
        self.assertEqual(set(matcher.split('|')), {'startup', 'resume', 'clear', 'compact'})
        self.assertIn('"$CLAUDE_PROJECT_DIR/scripts/cloud_session.py" start', handler['command'])

    def test_the_commit_gate_matches_the_user_level_hook(self):
        (matcher, handler), = hooks()['PreToolUse']
        self.assertEqual(matcher, 'Bash')
        self.assertIn(f'"$CLAUDE_PROJECT_DIR/{hooks_step.COMMITS_MARK}" hook pre --cli claude', handler['command'])
        self.assertEqual(handler['timeout'], hooks_step.COMMITS_TIMEOUT)

    def test_the_commit_gate_blocks_in_the_cloud_only(self):
        (_, handler), = hooks()['PreToolUse']
        repo = self.temp / 'repo'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True, env=self.env(False))
        (repo / 'a.txt').write_text('a\n')
        subprocess.run(['git', '-C', str(repo), 'add', 'a.txt'], check=True, env=self.env(False))
        event = json.dumps({'session_id': 's', 'cwd': str(repo), 'hook_event_name': 'PreToolUse',
                            'tool_name': 'Bash', 'tool_input': {'command': 'git commit -m probe'}})
        state = str(self.temp / 'state')
        self.assertEqual(self.run_sh(handler['command'], False, event, SMALL_COMMITS_STATE=state), (0, ''))
        code, out = self.run_sh(handler['command'], True, event, SMALL_COMMITS_STATE=state)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['hookSpecificOutput']['permissionDecision'], 'deny')


if __name__ == '__main__':
    unittest.main()
