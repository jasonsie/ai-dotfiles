"""The rule: a feature does not name a CLI. What differs between the CLIs is an adapter's (lib/adapters);
a feature reads the command, its folder and the files from the Event and asks the adapter what a CLI can do.

A feature's code is scanned with `ast` (its docstrings and comments are prose, not code) for a string that is a
CLI's id or one of its tools' names, and for a comparison on a CLI id or on a tool (`event.tool`: ask `event.action`). A feature's own `feature.json` is not
scanned: a declaration is per CLI by design. The short list below holds what is allowed, each with its reason.

Run: python3 -m unittest discover -s scripts/tests -p 'test_cli_rule.py' -v
"""
import ast
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
import adapters  # noqa: E402
import features  # noqa: E402

# Code outside a feature folder that is a feature, until its folder moves (the layout's status ticket).
FEATURE_FILES = ('skills/daily-log', 'scripts/statusline.py', 'scripts/cloud_session.py')
# (file, the string) -> why it may stay. A reason says what the string is, in a sentence.
ALLOWED = {
    ('skills/herdr-title/scripts/herdr_title.py', 'claude'):
        'the `claude -p` binary it starts to ask a small model; Claude Code run as a tool, not the session\'s CLI',
    ('skills/daily-log/scripts/day_pass.py', 'claude'):
        'the `claude -p` binary the day pass starts to write the log; Claude Code run as a tool, not a session\'s CLI',
    ('scripts/statusline.py', 'claude'):
        'the name a model gateway gives Anthropic as a provider (`codex/gpt-6` names another); not a session\'s CLI',
    ('skills/daily-log/scripts/day_pass.py', 'Bash'):
        'the value of `claude --tools`, a flag of that same `claude -p` call: it lets the writer run one command',
}
CLI_IDS = frozenset(adapters.CLIS)
ACTIONS = frozenset(features.ACTIONS)
# Tool names no feature may write, less the plain words that are also actions or programs (Pi's `bash`, `find`...).
PLAIN_WORDS = ACTIONS | {'write', 'bash', 'find', 'ls', 'grep'}
TOOL_NAMES = frozenset(name for cli in adapters.CLIS for names in adapters.get(cli).tools.values()
                       for name in names) - PLAIN_WORDS


def docstrings(tree):
    """The nodes of the docstrings in a module, its classes and its functions."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(first.value)
    return found


def names_a_cli(node):
    """Whether an operand of a comparison is a CLI's id held in a variable: `x.cli`, `x['cli']`, `cli`."""
    return ((isinstance(node, ast.Attribute) and node.attr == 'cli') or (isinstance(node, ast.Name) and node.id == 'cli')
            or (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == 'cli'))


def names_a_tool(node):
    """Whether an operand of a comparison is a tool's name held in a variable: `event.tool`."""
    return isinstance(node, ast.Attribute) and node.attr == 'tool'


def violations(path):
    """[(line, what)] a feature's Python file names: every string and comparison, the list not yet applied."""
    tree = ast.parse(Path(path).read_text())
    prose = docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in prose:
            if node.value in CLI_IDS or node.value in TOOL_NAMES:
                found.append((node.lineno, f'the string {node.value!r}'))
        elif isinstance(node, ast.Compare) and any(names_a_cli(side) for side in [node.left, *node.comparators]):
            found.append((node.lineno, 'a comparison on a CLI id'))
        elif isinstance(node, ast.Compare) and any(names_a_tool(side) for side in [node.left, *node.comparators]):
            found.append((node.lineno, 'a comparison on a tool name'))  # event.action says what a tool does
    return found


def feature_files(root):
    """The Python files of every feature under `root`: its folder's, less its tests."""
    folders = [feature.folder for feature in features.find(root)]
    paths = [Path(root, extra) for extra in FEATURE_FILES]
    paths = [path for extra in paths for path in ([extra] if extra.is_file() else extra.rglob('*.py'))]
    for folder in folders:
        paths += sorted(folder.rglob('*.py'))
    return sorted({path for path in paths if '__pycache__' not in path.parts})


def allowed(relative, what):
    return (relative, what.split("'")[1] if "'" in what else '') in ALLOWED


def named(root):
    """['<file>:<line> <what>'] for every name in the features under `root` that the list does not allow."""
    out = []
    for path in feature_files(root):
        relative = path.relative_to(root).as_posix()
        out += [f'{relative}:{line} {what}' for line, what in violations(path) if not allowed(relative, what)]
    return out


class RuleTest(unittest.TestCase):
    def test_no_feature_in_the_repo_names_a_cli(self):
        self.assertEqual(named(ROOT), [])

    def test_every_allowed_name_has_a_reason_and_still_occurs(self):
        seen = set()
        for path in feature_files(ROOT):
            relative = path.relative_to(ROOT).as_posix()
            seen |= {(relative, what.split("'")[1]) for _, what in violations(path) if "'" in what}
        for entry, reason in ALLOWED.items():
            self.assertTrue(reason.strip(), entry)
            self.assertIn(entry, seen, f'{entry} is on the list but no longer in the code: take it off')

    def test_a_fixture_feature_that_names_a_cli_fails_the_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, 'features/rogue')
            (folder / 'scripts').mkdir(parents=True)
            (folder / 'feature.json').write_text(json.dumps({'version': 1, 'cloud': False}))
            (folder / 'scripts/rogue.py').write_text(textwrap.dedent('''
                """Prose may say Claude Code, codex or agy: a docstring is not scanned."""
                TABLE = {'codex': 1}


                def hook(event):
                    if event.cli == 'pi':
                        return None
                    if event.tool in names:
                        return 'bash' if event.tool == 'bash' else None
                    return 'apply_patch' if event.tool == 'Bash' else None
            '''))
            found = named(Path(tmp))
        self.assertEqual(sorted(found.split(' ', 1)[1] for found in found),
                         ['a comparison on a CLI id', 'a comparison on a tool name', 'a comparison on a tool name',
                          'a comparison on a tool name', "the string 'Bash'", "the string 'apply_patch'",
                          "the string 'codex'", "the string 'pi'"])
        self.assertTrue(all(where.startswith('features/rogue/scripts/rogue.py:') for where in found))

    def test_a_fixture_feature_that_only_asks_the_event_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, 'features/tidy')
            (folder / 'scripts').mkdir(parents=True)
            (folder / 'feature.json').write_text(json.dumps({'version': 1, 'cloud': False}))
            (folder / 'scripts/tidy.py').write_text(textwrap.dedent('''
                def hook(event):
                    return event.command if event.action == 'shell' and event.adapter.enters_worktree else None
            '''))
            self.assertEqual(named(Path(tmp)), [])


if __name__ == '__main__':
    unittest.main()
