"""lib/features.py: features are found by their folders and each feature.json is checked strictly.

Run: python3 -m unittest discover -s scripts/tests -p 'test_features.py' -v
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
import features  # noqa: E402

GOOD = {'version': 1, 'cloud': False, 'hooks': {
    'module': 'hook.py', 'order': 5, 'budget': {'pre': 2, 'end': 1},
    'wants': {'claude': {'pre': ['edit', 'shell'], 'end': True}, 'pi': {'pre': True}}}}


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='features 空間 ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def declare(self, name, data, top='features'):
        folder = self.root / top / name
        folder.mkdir(parents=True)
        (folder / 'hook.py').write_text('def hook(event):\n    return None\n')
        (folder / 'cmd.py').write_text('print("ran")\n')
        (folder / features.DECLARATION).write_text(json.dumps(data))
        return folder / features.DECLARATION


class FindTest(Fixture):
    def test_this_repos_features_in_the_doors_order(self):
        found = features.find()
        self.assertEqual([f.name for f in found], ['worktree-guard', 'small-commits', 'herdr-title'])
        for feature in found:
            assert feature.module is not None
            self.assertTrue(feature.module.is_file(), feature.name)
        self.assertEqual([f.name for f in found if f.cloud], ['small-commits'])

    def test_a_folder_with_a_declaration_is_a_feature_in_features_or_skills_and_order_decides(self):
        self.declare('late', {**GOOD, 'hooks': {**GOOD['hooks'], 'order': 9}})
        self.declare('early', {**GOOD, 'hooks': {**GOOD['hooks'], 'order': 1}}, top='skills')
        (self.root / 'skills' / 'plain').mkdir()  # a skill with no declaration is no feature
        self.declare('commands-only', {'version': 1, 'cloud': True})
        self.assertEqual([f.name for f in features.find(self.root)], ['commands-only', 'early', 'late'])

    def test_two_features_with_one_name_are_refused(self):
        self.declare('twin', GOOD)
        self.declare('twin', GOOD, top='skills')
        with self.assertRaisesRegex(ValueError, 'a second feature named twin'):
            features.find(self.root)

    def test_what_a_feature_wants(self):
        feature = features.load(self.declare('a', GOOD))
        assert feature.module is not None
        self.assertEqual((feature.order, feature.budget, feature.module.name), (5, {'pre': 2, 'end': 1}, 'hook.py'))
        self.assertTrue(feature.wanted('claude', 'pre', 'edit'))
        self.assertFalse(feature.wanted('claude', 'pre', 'read'))
        self.assertTrue(feature.wanted('claude', 'end', 'other'))  # every call
        self.assertTrue(feature.wanted('pi', 'pre', 'other'))
        self.assertFalse(feature.wanted('codex', 'pre', 'edit'))  # a CLI it does not name
        self.assertIsNone(feature.tools('pi', 'pre'))


class CheckTest(Fixture):
    def refused(self, data, why):
        path = self.declare('bad', data)
        with self.assertRaises(ValueError) as caught:
            features.load(path)
        self.assertIn(str(path), str(caught.exception))
        self.assertIn(why, str(caught.exception))
        for item in self.root.iterdir():  # one at a time
            shutil.rmtree(item)

    def hooks(self, **changed):
        return {**GOOD, 'hooks': {**GOOD['hooks'], **changed}}

    def test_each_mistake_stops_it_and_names_the_file(self):
        cases = [
            ({**GOOD, 'extra': 1}, 'unknown key "extra"'),
            ({**GOOD, 'version': 2}, '"version": 1'),
            ({**GOOD, 'cloud': 'yes'}, '"cloud" must be true or false'),
            (self.hooks(when='never'), 'unknown key "hooks.when"'),
            ({**GOOD, 'hooks': {k: v for k, v in GOOD['hooks'].items() if k != 'order'}}, 'missing "order"'),
            (self.hooks(module='../x.py'), 'a path inside the folder'),
            (self.hooks(module='gone.py'), 'no file gone.py'),
            (self.hooks(order='first'), 'whole number'),
            (self.hooks(wants={'gemini': {'pre': True}}), "no hook format for 'gemini'"),
            (self.hooks(wants={'agy': {'prompt': True}}), "agy has no 'prompt' event"),
            (self.hooks(wants={'codex': {'start': True}}), "codex has no 'start' event"),
            (self.hooks(wants={'claude': {'end': ['shell']}}), '"hooks.wants.claude.end" must be true'),
            (self.hooks(wants={'claude': {'pre': ['write']}}), 'must be true or a list of edit, shell'),
            (self.hooks(wants={'claude': {'pre': []}}), 'must be true or a list'),
            (self.hooks(budget={'pre': 2}), 'no time for end'),
            (self.hooks(budget={'pre': 2, 'end': 1, 'stop': 1}), "no CLI wants 'stop'"),
            (self.hooks(budget={'pre': 0, 'end': 1}), 'above 0'),
        ]
        for data, why in cases:
            with self.subTest(why):
                self.refused(data, why)

    def test_a_file_that_is_not_json_names_itself(self):
        folder = self.root / 'features' / 'broken'
        folder.mkdir(parents=True)
        (folder / features.DECLARATION).write_text('{')
        with self.assertRaisesRegex(ValueError, 'broken/feature.json'):
            features.find(self.root)


COMMANDS = {'hello': {'run': 'cmd.py', 'help': 'says hello', 'usage': '[name]'},
            'git push': {'run': 'cmd.py', 'help': 'pushes', 'args': ['push']},
            'git pr': {'run': 'cmd.py', 'help': 'opens the PR'}}


class CommandsTest(Fixture):
    def commands(self, **changed):
        return {'version': 1, 'cloud': False, 'commands': {**COMMANDS, **changed}}

    def test_what_a_feature_adds(self):
        feature = features.load(self.declare('a', self.commands()))
        self.assertEqual(sorted(feature.commands), ['git pr', 'git push', 'hello'])
        hello, push = feature.commands['hello'], feature.commands['git push']
        self.assertEqual((hello.run, hello.help, hello.usage, hello.args),
                         (feature.folder / 'cmd.py', 'says hello', '[name]', ()))
        self.assertEqual((push.usage, push.args), ('', ('push',)))
        self.assertIsNone(feature.module)  # commands alone make no hooks

    def test_each_mistake_stops_it_and_names_the_file(self):
        cases = [
            ({'hello': {'run': 'cmd.py', 'help': 'x', 'extra': 1}}, 'unknown key "commands.hello.extra"'),
            ({'hello': {'help': 'x'}}, '"commands.hello" is missing "run"'),
            ({'hello': {'run': 'cmd.py'}}, '"commands.hello" is missing "help"'),
            ({'hello': {'run': '../cmd.py', 'help': 'x'}}, '"commands.hello.run" must be a path inside the folder'),
            ({'hello': {'run': 'gone.py', 'help': 'x'}}, '"commands.hello.run": no file gone.py'),
            ({'hello': {'run': 'cmd.py', 'help': ''}}, '"commands.hello.help" must be text'),
            ({'hello': {'run': 'cmd.py', 'help': 'x', 'args': 'push'}}, '"commands.hello.args" must be a list of text'),
            ({'Hello World': {'run': 'cmd.py', 'help': 'x'}}, 'one or two lowercase words'),
            ({'a b c': {'run': 'cmd.py', 'help': 'x'}}, 'one or two lowercase words'),
            ({'hook': {'run': 'cmd.py', 'help': 'x'}}, '"commands.hook" is the door\'s own'),
            ({'install now': {'run': 'cmd.py', 'help': 'x'}}, '"commands.install now" is the door\'s own'),
            ({'git': {'run': 'cmd.py', 'help': 'x'}}, '"commands.git" is a command and the start of "git push"'),
        ]
        for commands, why in cases:
            with self.subTest(why):
                path = self.declare('bad', {'version': 1, 'cloud': False, 'commands': {**commands, 'git push': COMMANDS['git push']}})
                with self.assertRaises(ValueError) as caught:
                    features.load(path)
                self.assertIn(str(path), str(caught.exception))
                self.assertIn(why, str(caught.exception))
                shutil.rmtree(self.root / 'features')

    def test_commands_must_be_an_object(self):
        path = self.declare('bad', {'version': 1, 'cloud': False, 'commands': ['hello']})
        with self.assertRaisesRegex(ValueError, '"commands" must be an object'):
            features.load(path)

    def test_two_features_may_not_share_a_command_or_a_group_word(self):
        self.declare('one', {'version': 1, 'cloud': False, 'commands': {'hello': COMMANDS['hello']}})
        self.declare('two', {'version': 1, 'cloud': False, 'commands': {'hello': COMMANDS['hello']}})
        with self.assertRaisesRegex(ValueError, 'two.*"hello" is already one\'s command'):
            features.find(self.root)
        shutil.rmtree(self.root / 'features' / 'two')
        self.declare('two', {'version': 1, 'cloud': False, 'commands': {'hello now': COMMANDS['hello']}})
        with self.assertRaisesRegex(ValueError, 'two.*"hello now" starts with one\'s command "hello"'):
            features.find(self.root)


if __name__ == '__main__':
    unittest.main()
