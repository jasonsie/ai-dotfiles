#!/usr/bin/env python3
"""Schedule the daily-log pass as a macOS LaunchAgent; writes unless --dry-run.

Every morning at 07:30 launchd runs one headless Claude Code session, `claude -p '/daily-log day'`,
which reads the evidence of yesterday's work that `daily-log day` prints and writes the journal
entries. This step only schedules that run. It writes one file,
~/Library/LaunchAgents/com.ai-dotfiles.daily-log-day.plist, and loads it with `launchctl bootstrap
gui/<uid>`, booting out a copy that is already loaded first, so a changed plist takes effect at once.
The plist runs the `claude` found on PATH when the step runs, as found: a symlink is not resolved,
so the job follows Claude Code's updates. Output and errors go to
~/Library/Logs/ai-dotfiles/daily-log-day.log. With no claude on PATH nothing is scheduled.

launchd starts a job with a minimal PATH, so the plist sets one: ~/.local/bin, where `daily-log` is
linked; the folder of the python3 on PATH when the step runs (daily-log needs 3.11+, and the system
python3 is older; a pyenv shim folder stays valid across versions); then /usr/bin and /bin, for git.
Run the step again after either moves and the plist is rewritten to match.

The plist carries an `ai-dotfiles` key. One without it or with another Label, and a symlink or
folder in its place, are refused, on install and on uninstall. The old plist is backed up before it
is replaced or removed. launchctl runs only when --home is the account's home folder by the user
database (not $HOME), so a run against another folder (a test, a trial) never touches launchd. If
loading fails the plist stays (launchd loads it at the next login) and the run reports the error.
--uninstall boots the job out and removes the plist; the log stays.
"""
import os
from pathlib import Path
import plistlib
import pwd
import shutil
import subprocess
import sys
from xml.parsers.expat import ExpatError

import installer

LABEL = 'com.ai-dotfiles.daily-log-day'
PLIST = f'Library/LaunchAgents/{LABEL}.plist'
LOG = 'Library/Logs/ai-dotfiles/daily-log-day.log'
MARKER = {'ai-dotfiles': 'daily-log day'}  # a key only this step writes: how it knows its own plist
HOUR, MINUTE = 7, 30
BACKUP = 'launchd'  # folder name under installer.STATE


def arguments(claude):
    """The command launchd runs. The prompt stays ahead of --allowedTools, which takes a list of
    values and would swallow it; the two rules go as one comma-joined value."""
    return [claude, '-p', '/daily-log day', '--model', 'sonnet',
            '--allowedTools', 'Bash(daily-log *),Read', '--max-turns', '40']


def python_folder():
    """The folder the job finds python3 in: that of the python running this step. A pyenv version
    folder changes with the version, so there pyenv's shims folder stands in, which stays valid
    (`which python3` cannot tell: pyenv puts the version's folder first on the PATH of the python it starts)."""
    folder = os.path.dirname(sys.executable or '')
    root = os.environ.get('PYENV_ROOT') or os.path.expanduser('~/.pyenv')  # pyenv's default root
    if folder and Path(folder).is_relative_to(Path(root) / 'versions'):
        shims = Path(root) / 'shims'
        if (shims / 'python3').is_file():
            return str(shims)
    return folder


def search_path(home):
    """The job's PATH, without repeats or an empty entry (which would mean the current folder)."""
    folders = [str(home / '.local/bin'), python_folder(), '/usr/bin', '/bin']
    return ':'.join(dict.fromkeys(folder for folder in folders if folder))


def real_home():
    """The account's home folder from the user database, whatever $HOME says: a run with HOME
    pointed at a test folder must never reach the user's launchd."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def content(home, claude):
    """The plist as bytes; its keys are sorted, so a run on the same machine writes the same bytes."""
    log = str(home / LOG)
    return plistlib.dumps({
        'Label': LABEL,
        **MARKER,
        'ProgramArguments': arguments(claude),
        'StartCalendarInterval': {'Hour': HOUR, 'Minute': MINUTE},
        'RunAtLoad': False,
        'WorkingDirectory': str(home),
        'EnvironmentVariables': {'HOME': str(home), 'PATH': search_path(home)},
        'StandardOutPath': log,
        'StandardErrorPath': log,
    })


def ours(data):
    """True when `data` is a property list this step wrote: its Label and its marker."""
    try:
        found = plistlib.loads(data)
    except (ValueError, ExpatError):  # not a property list at all
        return False
    return (isinstance(found, dict) and found.get('Label') == LABEL
            and all(found.get(key) == value for key, value in MARKER.items()))


def plan(home, claude, uninstall=False):
    """[(path, before, after)] to write the plist for `claude`, or to remove it; empty when it is
    already as wanted, mode included (launchd refuses a plist others can write). What is there and
    is not our plist is refused, a symlink or a folder too."""
    path = home / PLIST
    before = installer.state(path)
    if before[0] == 'link':
        raise ValueError(f'Not created by this script (a symlink); refusing to write through it: {path}')
    if before[0] == 'other':
        raise ValueError(f'Not created by this script (not a file); refusing to replace: {path}')
    if before[0] == 'file' and not ours(before[1]):
        raise ValueError(f'Not created by this script; refusing to replace: {path}')
    after = ('absent',) if uninstall else ('file', content(home, claude), 0o644)
    return [] if after == before else [(path, before, after)]


def load(home, plist, uninstall):
    """Have launchd run the job from `plist` in the user's GUI session (a loaded copy goes first),
    or on `uninstall` only drop it. Does nothing unless `home` is the real home folder: a preview
    or test folder must never reach the user's launchd. Returns whether launchctl ran."""
    if home != real_home():
        return False
    domain = f'gui/{os.getuid()}'
    print(f'Run: launchctl bootout {domain}/{LABEL}')
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)  # not loaded: fine
    if not uninstall:
        print(f'Run: launchctl bootstrap {domain} {plist}')
        try:
            subprocess.run(['launchctl', 'bootstrap', domain, str(plist)],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            raise ValueError(f'launchctl bootstrap failed (exit {error.returncode}): '
                             f'{(error.stderr or "").strip()}; {plist} is written, '
                             f'and launchd loads it at the next login') from error
    return True


def install(home, apply=False, uninstall=False):
    """Write the plist and load it, or boot the job out and remove the plist; the number of changes."""
    claude = None
    if not uninstall:
        found = shutil.which('claude')
        if not found:
            print('launchd: claude not on PATH; nothing scheduled')
            return 0
        claude = os.path.abspath(found)  # absolute, not resolved; a relative PATH entry would not be
    changes = plan(home, claude, uninstall)
    installer.show(changes, apply)
    if apply and changes:
        plist = home / PLIST
        if uninstall:
            load(home, plist, True)  # the job goes before its file
        else:
            (home / LOG).parent.mkdir(parents=True, exist_ok=True, mode=0o700)  # launchd will not make it
        saved = installer.apply(home, changes, backup=BACKUP)
        if saved:
            print(f'Backup: {saved}')
        if not uninstall:
            load(home, plist, False)
    return len(changes)


def main():
    args = installer.parser(__doc__, cli_target=False).parse_args()
    return installer.finish('launchd', lambda: install(args.home, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
