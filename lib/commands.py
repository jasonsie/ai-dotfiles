"""commands: `ai-dotfiles <command>` runs what a feature's declaration adds, and --help prints from them.

The wrapper (scripts/ai-dotfiles) runs the door's own commands itself (OWN below, the one list of
them: the installer, the healthcheck, the status line and the hook door) and hands every other word
here. A feature adds a command in its feature.json (lib/features.py, "commands"): the script to run,
its line in --help, and for a step of a group (`ai-dotfiles git push`) a name of two words. This module
finds the features by their folders, so a feature whose folder moves, or a new one, needs no edit to the
wrapper or here; --help is printed from the same declarations, so no list of commands is kept by hand
beyond OWN.

The command runs in this process's place (os.execv) under the Python the wrapper chose, so its stdin,
terminal, dialogs and exit status are its own; every word after the command's name, flags included
(`ai-dotfiles worktree --help`), goes to it. A declaration that does not check stops the call and
names its file. The wrapper starts this file with $PYTHON or python3, the system's 3.9 among them, so
what it and lib/features.py load stays free of newer syntax.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as declared  # noqa: E402  (feature.json, found by folder)

# (name, usage line, what it does): the commands the wrapper runs itself.
OWN = (
    ('install', '[install] [flags]', 'apply the setup (scripts/install.sh)'),
    ('update', 'update [flags]', 'pull this repo, then install (install.sh --update)'),
    ('uninstall', 'uninstall [flags]', 'remove what points into this repo (scripts/uninstall.sh)'),
    ('check', 'check', 'verify live state (scripts/healthcheck.sh)'),
    ('statusline', 'statusline', 'the status line Claude Code and Antigravity run: session JSON in, lines out'),
    ('hook', 'hook <kind> --cli <cli>', "what every CLI hook runs: the event's JSON in, every feature's reply out"),
)
NOTE = 'Flags pass through, e.g. --dry-run, --target=claude; see each command\'s --help.'


def table(found):
    """{name: Command} of every command the features declare, by name."""
    return {name: command for feature in found for name, command in sorted(feature.commands.items())}


def help_text(found):
    lines = [(f'ai-dotfiles {usage}', text) for _, usage, text in OWN]
    lines += [(f'ai-dotfiles {name} {command.usage}'.rstrip(), command.help)
              for name, command in sorted(table(found).items())]
    width = max(len(left) for left, _ in lines) + 2
    body = '\n'.join(f'  {left.ljust(width)}{right}' for left, right in lines)
    return ("ai-dotfiles — run this repo's installer and its features' commands from any folder "
            f'(linked into ~/.local/bin).\n\nUsage:\n{body}\n  {NOTE}\n')


def resolve(commands, argv):
    """(Command, the words left) for the line, or (None, argv): the longest name that starts it wins."""
    for width in (2, 1):
        name = ' '.join(argv[:width])
        if len(argv) >= width and name in commands:
            return commands[name], argv[width:]
    return None, argv


def main(argv=None, root=declared.ROOT, stdout=None, stderr=None, execute=os.execv):
    """Exit status of one `ai-dotfiles <argv>` the door does not run itself; `execute` replaces this
    process with the command's script and does not return."""
    argv = sys.argv[1:] if argv is None else list(argv)
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    try:
        found = declared.find(root)
    except ValueError as error:
        print(f'[ERR] {error}', file=stderr)
        return 1
    if not argv or argv[0] in ('-h', '--help', 'help'):
        stdout.write(help_text(found))
        return 0
    commands = table(found)
    command, rest = resolve(commands, argv)
    if command is not None:
        execute(sys.executable, [sys.executable, str(command.run), *command.args, *rest])
        return 0
    steps = [name.split(' ')[1] for name in commands if name.startswith(argv[0] + ' ')]
    if steps:
        print(f'[ERR] ai-dotfiles {argv[0]} <step>: {", ".join(steps)}; got: {" ".join(argv[1:2])}', file=stderr)
    else:
        print(f'[ERR] Unknown command: {argv[0]}', file=stderr)
        stderr.write(help_text(found))
    return 1


if __name__ == '__main__':
    sys.exit(main())
