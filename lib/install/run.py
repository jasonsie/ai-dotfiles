#!/usr/bin/env python3
"""Run the install steps in lib/install/steps.py: install, uninstall, check, or print --help.

  python3 lib/install/run.py install [--dry-run] [--target=all|<cli>] [--cloud]
                                     [--instructions-only] [--replace-instructions] [--home DIR]
  python3 lib/install/run.py uninstall [--dry-run] [--target=all|<cli>] [--home DIR]
  python3 lib/install/run.py check [--home DIR]
  python3 lib/install/run.py help [install|uninstall]
  python3 lib/install/run.py args <command> [arguments]    # exit 1 on an argument the command refuses

scripts/install.sh, uninstall.sh and healthcheck.sh call it. Install runs each step in list order,
uninstall in reverse; every step prints `== name` and `name: N changes`, and the first one to fail
stops the run with exit status 1. check prints each step's checks as the healthcheck's lines.
"""
from dataclasses import replace
from pathlib import Path
import sys

import installer
import steps

ROOT = Path(__file__).resolve().parents[2]
ENTRY = {'install': 'install.sh', 'uninstall': 'uninstall.sh'}  # in scripts/; the header of each is its usage
SWITCHES = {  # the flags without a value that each command takes, and the Options field each sets
    'install': {'--dry-run': 'dry_run', '--cloud': 'cloud', '--replace-instructions': 'replace_instructions',
                '--instructions-only': 'instructions_only'},
    'uninstall': {'--dry-run': 'dry_run'},
    'check': {},
}
VALUES = {'install': ('--target', '--home'), 'uninstall': ('--target', '--home'), 'check': ('--home',)}
STEPS_HEADING = {
    'install': 'Steps, in order (each is idempotent, dry-run aware, and backs up before writing):',
    'uninstall': 'Steps, in reverse install order (each removes only what its installer created,\n'
                 'backs up before writing, and rolls back on failure):',
}
COMMANDS = 'install|uninstall|check|args|help'


class UnknownArgument(Exception):
    pass


def parse(command, argv):
    """(Options, instructions_only, help) from the arguments after the command; UnknownArgument for others."""
    given = {'target': 'all', 'home': Path.home().resolve()}
    flags = set()
    args = iter(argv)
    for arg in args:
        name, equals, value = arg.partition('=')
        if arg in ('--help', '-h'):
            return None, False, True
        if name in SWITCHES[command] and not equals:
            flags.add(SWITCHES[command][name])
        elif name in VALUES[command]:
            if not equals:
                value = next(args, None)
                if value is None:
                    raise UnknownArgument(arg)
            given[name[2:]] = Path(value).expanduser().resolve() if name == '--home' else value
        else:
            raise UnknownArgument(arg)
    cloud = 'cloud' in flags
    options = steps.Options(
        home=given['home'], target='claude' if cloud else given['target'], apply='dry_run' not in flags,
        uninstall=command == 'uninstall', cloud=cloud, live=installer.live_root(ROOT),
        replace_instructions='replace_instructions' in flags)
    return options, 'instructions_only' in flags, False


def header(command):
    """The leading comment of the command's entry script, which is its usage."""
    lines = (ROOT / 'scripts' / ENTRY[command]).read_text().splitlines()[1:]
    comment = []
    for line in lines:
        if not line.startswith('#'):
            break
        comment.append(line[1:].removeprefix(' '))
    return '\n'.join(comment)


def usage(command, modules):
    """The entry script's usage, then each step's line: SUMMARY on install, UNDO on uninstall."""
    if command == 'check':
        return 'Usage: run.py check [--home DIR]\nPrint each step\'s checks; exit 1 when one fails.'
    ordered = list(modules) if command == 'install' else list(reversed(modules))
    width = max(len(module.__name__) for module in ordered)
    lines = [header(command), '', STEPS_HEADING[command]]
    for module in ordered:
        number = list(modules).index(module) + 1
        text = module.SUMMARY if command == 'install' else module.UNDO
        lines.append(f'  {number}. {module.__name__:<{width}}  {text}')
    return '\n'.join(lines)


def preflight(options):
    """Check config/ai-clis.json and warn about a CLI folder override that disagrees with it; 1 when
    the registry is wrong."""
    try:
        installer.clis()
    except (OSError, ValueError) as error:
        print(f'clis: {error}', file=sys.stderr)
        return 1
    for warning in installer.check(options.home):
        print(warning, file=sys.stderr)
    return 0


def install(options, instructions_only, modules):
    if preflight(options):
        return 1
    # A cloud session's VM runs Claude Code alone, and Claude reads ~/.claude only once it exists.
    if options.cloud and options.apply:
        (options.home / '.claude').mkdir(parents=True, exist_ok=True)
    for module in modules:
        name = module.__name__
        print(f'== {name}')
        skip = getattr(module, 'CLOUD_SKIP', None)
        if options.cloud and skip:
            print(skip)
        elif installer.finish(name, lambda module=module: module.execute(options)):
            return 1
        if instructions_only and name == 'instructions':
            return 0
    print('Done. Verify: ai-dotfiles check' if options.apply else
          'Preview only: nothing written. Run again without --dry-run to write.')
    return 0


def uninstall(options, modules):
    if preflight(options):
        return 1
    for module in reversed(modules):
        print(f'== {module.__name__}')
        if installer.finish(module.__name__, lambda module=module: module.execute(options)):
            return 1
    print('Done. Reinstall: bash scripts/install.sh' if options.apply else
          'Preview only: nothing written. Run again without --dry-run to remove.')
    return 0


def check(options, modules):
    """Print each step's checks under `-- name`; 1 when any is FAIL."""
    # The live setup is measured against the main checkout, where this one is a linked worktree.
    live = options.live if options.live and (options.live / 'scripts/install.sh').is_file() else ROOT
    options = replace(options, live=live)
    failed = False
    for module in modules:
        checks = getattr(module, 'checks', None)
        if checks is None:
            continue
        print(f'-- {getattr(module, "CHECKS_TITLE", module.__name__)}')
        try:
            results = checks(options)
        except (OSError, ValueError, KeyError) as error:
            results = [('FAIL', f'{module.__name__} checks failed: {error}')]
        for status, message in results:
            assert status in steps.STATUSES, status
            print(f'  {status:<4}  {message}')
            failed = failed or status == 'FAIL'
    return int(failed)


def main(argv=None, modules=None):
    """Run a command; `modules` replaces the listed steps (a test adds one of its own)."""
    argv = sys.argv[1:] if argv is None else argv
    command, rest = (argv[0], argv[1:]) if argv else ('', [])
    if command == 'help':
        command, rest = (rest[0] if rest and rest[0] in ENTRY else 'install'), ['--help']
    check_only = command == 'args'  # `args <command> ...`: parse the arguments, run nothing
    if check_only:
        command, rest = (rest[0], rest[1:]) if rest else ('', [])
    if command not in SWITCHES:
        print(f'Usage: run.py {COMMANDS} [arguments]', file=sys.stderr)
        return 1
    modules = steps.load() if modules is None else modules
    try:
        options, instructions_only, helped = parse(command, rest)
    except UnknownArgument as error:
        print(f'[ERR] Unknown argument: {error}', file=sys.stderr)
        print(usage(command, modules), file=sys.stderr)
        return 1
    if helped:
        print(usage(command, modules))
        return 0
    if check_only:
        return 0
    if command == 'install':
        return install(options, instructions_only, modules)
    return uninstall(options, modules) if command == 'uninstall' else check(options, modules)


if __name__ == '__main__':
    sys.exit(main())
