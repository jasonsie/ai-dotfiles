"""features: the programs this repo runs, found by their folders, each described by its feature.json.

A feature is a program this repo runs: in a session, beside one, on a schedule or in CI. Its folder
holds its code, its tests, its skills and its declaration, feature.json; a folder that holds one is
a feature, and it is on. Nothing lists the features anywhere else: the installer (lib/install/
hooks.py) and the door (lib/door.py) both find them here, in features/<name>/ and, until each one
moves there, in skills/<name>/.

The declaration, checked strictly: an unknown key, a CLI the hook formats do not know, or an event a
CLI does not hand over stops the install and the door, and the error names the file.

  {"version": 1,
   "cloud": false,                          whether a cloud session runs the feature's hooks
   "hooks": {                               (optional) what the door calls the feature for:
     "module": "scripts/worktree_guard.py",   the file, in the folder, whose hook(event) the door calls
     "order": 10,                             its place among the features one event reaches: lower first
     "budget": {"pre": 60, "end": 60},        the seconds it may take, for each event it wants
     "wants": {                               per CLI (scripts/agent_hooks.py CLIS), the events (KINDS):
       "claude": {"pre": ["edit", "shell"],   a tool event (TOOL_KINDS) for the tools that do these
                  "end": true}}},            actions (edit, shell, read, ask, other), or true for every call
   "commands": {                            (optional) what `ai-dotfiles <name>` runs, and --help prints:
     "worktree": {"run": "scripts/worktree_guard.py",   the Python script, in the folder, that runs
                  "help": "agents' worktrees",          its line in --help
                  "usage": "<command>",                 (optional) what follows the name there
                  "args": ["reviewer"]},                (optional) words put before the rest of the line
     "git push": {...}}}                    a name of two words is a step of a group: `ai-dotfiles git push`

A command's name may not be one of the door's own (OWN_COMMANDS), nor another feature's; one feature's
command may not be the first word of another's. A feature may declare commands alone, with no hooks.

The module's hook(event) gets an agent_hooks.Event and returns a reply (Note, Deny, Rewrite, Shown,
Continue) or None; it may define failed(error), the note the door gives in its place when it fails
before a tool call. Why the door runs features in order, in one process: lib/door.py.
Python 3.11+, stdlib only (the command table below also loads on the system's 3.9: `--help` runs there).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import numbers
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats: their kinds and tools)

DECLARATION = 'feature.json'
FOLDERS = ('features', 'skills')  # where a feature's folder is found: features/ once it has moved there
ACTIONS = ('edit', 'shell', 'read', 'ask', 'other')  # what a tool does (agent_hooks.Event.action)
KEYS = {'version', 'cloud', 'hooks', 'commands'}
HOOK_KEYS = {'module', 'order', 'budget', 'wants'}
COMMAND_KEYS = {'run', 'help', 'usage', 'args'}
COMMAND_REQUIRED = ('run', 'help')
OWN_COMMANDS = ('install', 'update', 'uninstall', 'check', 'statusline', 'hook', 'status', 'help')  # the door's: no feature takes one
COMMAND_NAME = re.compile(r'[a-z][a-z0-9-]*( [a-z][a-z0-9-]*)?')  # a word, or a group and its step


@dataclass(frozen=True)
class Command:
    """An `ai-dotfiles <name>` a feature adds: the script it runs, with `args` before the rest of the line."""
    name: str                 # one word, or a group and its step: "git push"
    run: Path
    help: str
    usage: str = ''           # what follows the name in --help
    args: tuple = ()


@dataclass(frozen=True)
class Feature:
    name: str                 # the folder's name
    folder: Path
    cloud: bool               # a cloud session runs its hooks
    module: Path | None = None  # the file whose hook(event) the door calls; None: no hooks
    order: int = 0
    budget: dict = field(default_factory=dict)  # {kind: seconds}
    wants: dict = field(default_factory=dict)   # {cli: {kind: None (every call) or frozenset of actions}}
    commands: dict = field(default_factory=dict)  # {name: Command}

    def tools(self, cli, kind):
        """None when the feature wants every call of `kind` from `cli`; else the actions it wants
        (empty when it wants none)."""
        return self.wants.get(cli, {}).get(kind, frozenset())

    def wanted(self, cli, kind, action):
        tools = self.tools(cli, kind)
        return tools is None or action in tools


def find(root=ROOT):
    """Every feature under `root`, in the door's order (order, then name). Two with one name are refused."""
    found = {}
    for top in FOLDERS:
        for path in sorted(Path(root, top).glob(f'*/{DECLARATION}')):
            feature = load(path)
            if feature.name in found:
                raise ValueError(f'{path}: a second feature named {feature.name} (the first: {found[feature.name].folder})')
            found[feature.name] = feature
    check_commands(found.values())
    return sorted(found.values(), key=lambda feature: (feature.order, feature.name))


def check_commands(found):
    """ValueError when two features' commands meet: one name twice, or a name that is another's group."""
    owner = {}
    for feature in found:
        for name in feature.commands:
            if name in owner:
                raise ValueError(f'{feature.folder / DECLARATION}: "{name}" is already {owner[name]}\'s command')
            owner[name] = feature.name
    for feature in found:
        for name in feature.commands:
            group = name.split(' ')[0]
            if ' ' in name and group in owner and owner[group] != feature.name:
                raise ValueError(f'{feature.folder / DECLARATION}: "{name}" starts with {owner[group]}\'s command "{group}"')


def load(path):
    """The Feature a feature.json declares; ValueError naming the file when it does not check."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f'{path}: {error}') from error
    try:
        return parse(data, path.parent)
    except ValueError as error:
        raise ValueError(f'{path}: {error}') from None


def parse(data, folder):
    if not isinstance(data, dict):
        raise ValueError('expected a JSON object')
    unknown(data, KEYS)
    if data.get('version') != 1:
        raise ValueError('expected "version": 1')
    if not isinstance(data.get('cloud'), bool):
        raise ValueError('"cloud" must be true or false')
    feature = Feature(folder.name, folder, data['cloud'], commands=parse_commands(data.get('commands', {}), folder))
    hooks = data.get('hooks')
    if hooks is None:
        return feature
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" must be an object')
    unknown(hooks, HOOK_KEYS, 'hooks.')
    missing = sorted(HOOK_KEYS - set(hooks))
    if missing:
        raise ValueError('"hooks" is missing ' + ', '.join(f'"{key}"' for key in missing))
    module = hooks['module']
    if not isinstance(module, str) or Path(module).is_absolute() or '..' in Path(module).parts:
        raise ValueError('"hooks.module" must be a path inside the folder')
    if not (folder / module).is_file():
        raise ValueError(f'"hooks.module": no file {module}')
    if not isinstance(hooks['order'], int) or isinstance(hooks['order'], bool):
        raise ValueError('"hooks.order" must be a whole number')
    wants = parse_wants(hooks['wants'])
    budget = parse_budget(hooks['budget'], {kind for kinds in wants.values() for kind in kinds})
    return replace(feature, module=folder / module, order=hooks['order'], budget=budget, wants=wants)


def parse_commands(commands, folder):
    if not isinstance(commands, dict):
        raise ValueError('"commands" must be an object')
    parsed = {}
    for name, entry in commands.items():
        where = f'"commands.{name}"'
        if not COMMAND_NAME.fullmatch(name):
            raise ValueError(f'{where} must be one or two lowercase words')
        if name.split(' ')[0] in OWN_COMMANDS:
            raise ValueError(f"{where} is the door's own command")
        if not isinstance(entry, dict):
            raise ValueError(f'{where} must be an object')
        unknown(entry, COMMAND_KEYS, f'commands.{name}.')
        for key in COMMAND_REQUIRED:
            if key not in entry:
                raise ValueError(f'{where} is missing "{key}"')
        run = entry['run']
        if not isinstance(run, str) or Path(run).is_absolute() or '..' in Path(run).parts:
            raise ValueError(f'"commands.{name}.run" must be a path inside the folder')
        if not (folder / run).is_file():
            raise ValueError(f'"commands.{name}.run": no file {run}')
        for key in ('help', 'usage'):
            if key in entry and not (isinstance(entry[key], str) and (entry[key] or key == 'usage')):
                raise ValueError(f'"commands.{name}.{key}" must be text')
        args = entry.get('args', [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError(f'"commands.{name}.args" must be a list of text')
        parsed[name] = Command(name, folder / run, entry['help'], entry.get('usage', ''), tuple(args))
    for name in parsed:
        steps = sorted(other for other in parsed if other.startswith(name + ' '))
        if steps:
            raise ValueError(f'"commands.{name}" is a command and the start of "{steps[0]}"')
    return parsed


def parse_wants(wants):
    if not isinstance(wants, dict) or not wants:
        raise ValueError('"hooks.wants" must name at least one CLI')
    parsed = {}
    for cli, kinds in wants.items():
        if cli not in agent_hooks.CLIS:
            raise ValueError(f'"hooks.wants": no hook format for {cli!r} ({", ".join(agent_hooks.CLIS)})')
        if not isinstance(kinds, dict):
            raise ValueError(f'"hooks.wants.{cli}" must be an object')
        parsed[cli] = {}
        for kind, tools in kinds.items():
            if kind not in agent_hooks.KINDS[cli]:
                raise ValueError(f'"hooks.wants.{cli}": {cli} has no {kind!r} event '
                                 f'(it has {", ".join(agent_hooks.KINDS[cli])})')
            if tools is True:
                parsed[cli][kind] = None
            elif (kind in agent_hooks.TOOL_KINDS and isinstance(tools, list) and tools
                  and all(isinstance(action, str) and action in ACTIONS for action in tools)):
                parsed[cli][kind] = frozenset(tools)
            else:
                allowed = f'true or a list of {", ".join(ACTIONS)}' if kind in agent_hooks.TOOL_KINDS else 'true'
                raise ValueError(f'"hooks.wants.{cli}.{kind}" must be {allowed}')
    return parsed


def parse_budget(budget, kinds):
    if not isinstance(budget, dict):
        raise ValueError('"hooks.budget" must be an object')
    for kind, seconds in budget.items():
        if kind not in kinds:
            raise ValueError(f'"hooks.budget.{kind}": no CLI wants {kind!r} of this feature')
        if not isinstance(seconds, numbers.Real) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError(f'"hooks.budget.{kind}" must be a number of seconds above 0')
    missing = sorted(kinds - set(budget))
    if missing:
        raise ValueError('"hooks.budget" has no time for ' + ', '.join(missing))
    return dict(budget)


def unknown(data, keys, prefix=''):
    extra = sorted(set(data) - keys)
    if extra:
        raise ValueError('unknown key ' + ', '.join(f'"{prefix}{key}"' for key in extra))
