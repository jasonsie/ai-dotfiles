"""A cloud session reads only the clone: this repo's .claude/settings.json gives it the global
rules, the skills, the ai-dotfiles command (scripts/cloud_session.py) and the door, which runs the
commit gate alone there."""
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
skills_step = load('install/skills.py')

CLOUD = ROOT / 'config/cloud.json'
SKILLS = skills_step.repo_skills(ROOT)  # {name: folder}, bundles flattened
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
    config of its own; its config/, lib/, scripts/ and skills/ are links to this repo's."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.project = self.temp / 'clone'
        self.project.mkdir()
        for name in ('config', 'lib', 'scripts', 'skills'):
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


def local_only():
    """{skill: why it stays on the Mac} from config/cloud.json."""
    return json.loads(CLOUD.read_text())['local_only']


class SkillLinksTest(Sandbox):
    """In a cloud session, start links each skill a cloud session can run into .claude/skills/."""

    def links(self):
        folder = self.project / '.claude/skills'
        return {p.name: p for p in folder.iterdir()} if folder.is_dir() else {}

    def test_a_cloud_session_gets_every_skill_but_the_local_only_ones(self):
        code, out = self.start(True, CLAUDE_ENV_FILE=str(self.temp / 'env.sh'))
        self.assertEqual(code, 0)
        self.assertIs(self.reply(out)['reloadSkills'], True, 'made after discovery: re-scan')
        self.assertEqual(sorted(self.links()), sorted(set(SKILLS) - set(local_only())))

    def test_each_link_is_relative_and_lands_on_its_skill(self):
        self.start(True, CLAUDE_ENV_FILE=str(self.temp / 'env.sh'))
        for name, link in self.links().items():
            with self.subTest(name):
                self.assertTrue(link.is_symlink(), 'a link, never a copy')
                self.assertFalse(os.path.isabs(os.readlink(link)), 'relative, so it resolves in any clone')
                self.assertEqual(link.resolve(), SKILLS[name].resolve())

    def test_a_second_start_changes_nothing(self):
        env_file = str(self.temp / 'env.sh')
        self.start(True, CLAUDE_ENV_FILE=env_file)
        before = {name: os.readlink(link) for name, link in self.links().items()}
        _, out = self.start(True, CLAUDE_ENV_FILE=env_file)
        self.assertNotIn('reloadSkills', self.reply(out))
        self.assertEqual({name: os.readlink(link) for name, link in self.links().items()}, before)

    def test_a_mac_session_links_nothing(self):
        self.start(False, CLAUDE_ENV_FILE=str(self.temp / 'env.sh'))
        self.assertFalse((self.project / '.claude').exists())

    def test_links_it_cannot_make_are_said_and_the_rules_still_come(self):
        (self.project / '.claude').mkdir()
        (self.project / '.claude/skills').write_text('a file where the folder goes\n')
        code, out = self.start(True, CLAUDE_ENV_FILE=str(self.temp / 'env.sh'))
        self.assertEqual(code, 0)
        context = self.reply(out)['additionalContext']
        self.assertIn('could not be linked', context)
        self.assertIn(RULES, context)

    def test_git_ignores_the_links(self):
        ignored = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '-q', str(ROOT / '.claude/skills/grilling')])
        self.assertEqual(ignored.returncode, 0, 'a link made in a cloud clone must never be committed')

    def test_each_local_only_skill_is_a_skill_and_says_why(self):
        self.assertEqual(json.loads(CLOUD.read_text())['version'], 1)
        for name, why in local_only().items():
            with self.subTest(name):
                self.assertIn(name, SKILLS)
                self.assertIsInstance(why, str)
                self.assertTrue(why.strip())


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

    def test_the_door_has_one_entry_per_event_the_cloud_features_want_as_the_hooks_step_writes_them(self):
        cloud = [feature for feature in hooks_step.declared.find() if feature.cloud]
        wanted = {event: (kind, matcher, timeout) for event, kind, matcher, timeout in hooks_step.entries('claude', cloud)}
        door = {event: entries for event, entries in hooks().items()
                if any('/scripts/ai-dotfiles" hook ' in handler['command'] for _, handler in entries)}
        self.assertEqual(set(door), set(wanted))
        for event, ((matcher, handler),) in door.items():
            kind, wanted_matcher, timeout = wanted[event]
            self.assertEqual((matcher, handler['timeout']), (wanted_matcher, timeout), event)
            self.assertEqual(handler['command'],
                             f'{GATE}"$CLAUDE_PROJECT_DIR/scripts/ai-dotfiles" hook {kind} --cli claude{TAIL}')

    def repo(self, flow=False):
        """A repo with a file staged, in which a `git commit -m probe` gets the commit gate's no."""
        repo = self.temp / 'repo'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True, env=self.env(False))
        (repo / 'a.txt').write_text('a\n')
        subprocess.run(['git', '-C', str(repo), 'add', 'a.txt'], check=True, env=self.env(False))
        if flow:  # worktree-guard would stop any change to this main checkout on a Mac
            subprocess.run(['git', '-C', str(repo), 'config', '--local', 'worktree-guard.flow', 'true'], check=True)
        return repo

    def gate(self, repo, command, remote):
        (_, handler), = hooks()['PreToolUse']
        event = json.dumps({'session_id': 's', 'cwd': str(repo), 'hook_event_name': 'PreToolUse',
                            'tool_name': 'Bash', 'tool_input': {'command': command}})
        return self.run_sh(handler['command'], remote, event, SMALL_COMMITS_STATE=str(self.temp / 'state'),
                           WORKTREE_GUARD_STATE=str(self.temp / 'guard'))

    def test_the_commit_gate_blocks_in_the_cloud_only(self):
        repo = self.repo()
        self.assertEqual(self.gate(repo, 'git commit -m probe', False), (0, ''))
        code, out = self.gate(repo, 'git commit -m probe', True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_in_the_cloud_the_door_runs_the_commit_gate_and_nothing_else(self):
        repo = self.repo(flow=True)
        _, out = self.gate(repo, 'git commit -m probe', True)
        self.assertTrue(json.loads(out)['hookSpecificOutput']['permissionDecisionReason'].startswith('small-commits'))
        good = "git commit -m 'feat(x): add a' -m 'Why: a test\nScope: x\nVerified: none'"
        self.assertEqual(self.gate(repo, good, True), (0, ''))  # the guard, which would stop it on a Mac, does not run
        self.assertFalse((self.temp / 'guard').exists())


if __name__ == '__main__':
    unittest.main()
