#!/usr/bin/env python3
"""The status line Claude Code and Antigravity show: the session's JSON on stdin, lines on stdout.

Both CLIs run `ai-dotfiles statusline` (the `statusLine` key config/cli-settings.json enforces)
whenever the session changes and show what it prints. Codex renders the same items itself from
its `tui.status_line` list, and Pi's own footer already shows them. Up to three lines:

  📁 ~/repo  🌿 main ⎇ agent-2  🤖 Fable 5.1 · max · ⚡fast  📟 v2.1.318
  🧠 Context: 93% [=========-]
  ⏳ 5h 23% → 14:00  7d 41% → Thu 08:00  💰 $0.12

Line 1: the folder; the git branch (the short commit when detached) and, inside a linked
worktree, its name; the model with its effort when the CLI sends one, "thinking off" and
"⚡fast" only when so; the CLI's version. Line 2: the context window left, from the CLI's own
percentage, "?" before the first reply. Line 3: the rate-limit windows and the cost, each when
the CLI sends it; no line when it sends neither. A window shows how much of it is used and the
local time it resets (with the weekday when that is not today); a window whose reset has passed
is left out, since its figure is stale. The figures are those of the session's last API
response: the CLI re-runs the script on every change in the session and at each reset time, not
on a clock, so a figure can lag what another session has spent since. The two CLIs name fields
differently (Claude: effort.level, cost.total_cost_usd, rate_limits with resets_at; Antigravity:
model.effort, cost.total_usd, quota with reset_time); each lookup tries both. The script never
fails: on bad input it prints what it can and exits 0, so a broken payload cannot blank the line.
Runs on any python3 (3.9+).
"""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

COLORS = {
    'dir': 117, 'git': 150, 'model': 147, 'detail': 245, 'version': 249,
    'ctx': 158, 'ctx_warn': 215, 'ctx_crit': 203, 'limits': 222, 'cost': 220,
}
RESET = '\033[0m'
WINDOWS = (('five_hour', '5h'), ('seven_day', '7d'), ('spend_limit', 'spend'))  # Claude's rate_limits
GIT_FACTS = ['rev-parse', '--abbrev-ref', 'HEAD', '--git-dir', '--git-common-dir', '--show-toplevel']


def paint(color, text):
    return f'\033[38;5;{COLORS[color]}m{text}{RESET}'


def get(data, *path, default=None):
    """The value at a key path, or `default` when any step is missing or null."""
    node = data
    for key in path:
        if not isinstance(node, dict) or node.get(key) is None:
            return default
        node = node[key]
    return node


def tilde(folder, home=None):
    """The folder with the home prefix shown as ~."""
    home = (home or os.path.expanduser('~')).rstrip('/')
    if folder == home:
        return '~'
    return '~' + folder[len(home):] if folder.startswith(home + '/') else folder


def git(folder, args, run=subprocess.run):
    """The lines git prints for `args` in `folder`, or [] when it fails or takes too long."""
    try:
        done = run(['git', '-C', folder, *args], capture_output=True, text=True, timeout=2,
                   env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, subprocess.SubprocessError):
        return []
    return done.stdout.splitlines() if done.returncode == 0 else []


def git_facts(folder, run=subprocess.run):
    """(branch, worktree): the branch or short commit, and a linked worktree's folder name; '' when unknown."""
    lines = git(folder, GIT_FACTS, run)
    if len(lines) < 4:
        return '', ''
    branch, git_dir, common_dir, top = lines[:4]
    if branch == 'HEAD':  # detached
        branch = ''.join(git(folder, ['rev-parse', '--short', 'HEAD'], run)[:1])
    base = Path(folder)
    linked = (base / git_dir).resolve() != (base / common_dir).resolve()
    return branch, Path(top).name if linked else ''


def model_segment(data):
    name = get(data, 'model', 'display_name') or get(data, 'model', 'id') or '?'
    effort = get(data, 'effort', 'level') or get(data, 'model', 'effort')
    if effort and name.lower().endswith(f'({effort.lower()})'):
        name = name[:-len(effort) - 2].rstrip()  # Antigravity repeats the effort in the name
    details = [effort] if effort else []
    if get(data, 'thinking', 'enabled') is False:
        details.append('thinking off')
    if get(data, 'fast_mode') is True:
        details.append('⚡fast')
    return paint('model', name) + paint('detail', ''.join(f' · {d}' for d in details))


def remaining(data):
    """Percent of the context window left: the CLI's figure, else computed from the last call, else None."""
    percent = get(data, 'context_window', 'remaining_percentage')
    if percent is None:
        usage = get(data, 'context_window', 'current_usage', default={})
        tokens = sum(usage.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        size = get(data, 'context_window', 'context_window_size') or 200000
        percent = 100 - tokens * 100 / size if tokens > 0 else None
    return None if percent is None else int(max(0, min(100, percent)))


def context_line(data):
    left = remaining(data)
    filled = 0 if left is None else left // 10
    color = 'ctx' if left is None or left > 40 else 'ctx_warn' if left > 20 else 'ctx_crit'
    label = '?' if left is None else f'{left}%'
    return '🧠 ' + paint(color, f'Context: {label} [{"=" * filled}{"-" * (10 - filled)}]')


def epoch(value):
    """A reset time as epoch seconds: Claude's resets_at (a number) or Antigravity's reset_time (ISO 8601,
    'Z' allowed); None when absent or unreadable."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None
    return None


def clock(at, now, tz=None):
    """'14:00' for a time today, 'Thu 08:00' for one on another day, in the local zone (or `tz`)."""
    when = datetime.fromtimestamp(at, tz)
    today = datetime.fromtimestamp(now, tz).date()
    return when.strftime('%H:%M' if when.date() == today else '%a %H:%M')


def limits(data, now=None):
    """(label, percent used, reset epoch or None) per window still running: Claude's rate-limit windows,
    then Antigravity's quota buckets (the share used, from the fraction left)."""
    now = time.time() if now is None else now
    found = []
    for key, label in WINDOWS:
        used = get(data, 'rate_limits', key, 'used_percentage')
        if used is not None:
            found.append((label, used, epoch(get(data, 'rate_limits', key, 'resets_at'))))
    for bucket, status in get(data, 'quota', default={}).items():
        fraction = get(status, 'remaining_fraction')
        if fraction is not None:
            reset = epoch(get(status, 'reset_time'))
            seconds = get(status, 'reset_in_seconds')
            if reset is None and isinstance(seconds, (int, float)):
                reset = now + seconds
            found.append((bucket, (1 - fraction) * 100, reset))
    return [(label, used, reset) for label, used, reset in found if reset is None or reset > now]


def usage_line(data, now=None, tz=None):
    now = time.time() if now is None else now
    parts = []
    windows = [paint('limits', f'{label} {round(used)}%') + (paint('detail', f' → {clock(reset, now, tz)}') if reset else '')
               for label, used, reset in limits(data, now)]
    if windows:
        parts.append('⏳ ' + '  '.join(windows))
    cost = get(data, 'cost', 'total_cost_usd')
    cost = get(data, 'cost', 'total_usd') if cost is None else cost
    if isinstance(cost, (int, float)) and cost > 0:
        parts.append('💰 ' + paint('cost', f'${cost:.2f}'))
    return '  '.join(parts)


def first_line(data, folder, facts):
    parts = ['📁 ' + paint('dir', tilde(folder))]
    branch, worktree = facts
    if branch:
        parts.append('🌿 ' + paint('git', branch + (f' ⎇ {worktree}' if worktree else '')))
    parts.append('🤖 ' + model_segment(data))
    version = get(data, 'version')
    if version:
        parts.append('📟 ' + paint('version', f'v{version}'))
    return '  '.join(parts)


def folder_of(data):
    return get(data, 'workspace', 'current_dir') or get(data, 'cwd') or os.getcwd()


def render(data, facts=None, now=None, tz=None):
    """The lines for one payload; `facts` is (branch, worktree), looked up in git when not given;
    `now` and `tz` fix the clock and zone the reset times are shown in (the system's when not given)."""
    folder = folder_of(data)
    lines = [first_line(data, folder, git_facts(folder) if facts is None else facts), context_line(data)]
    usage = usage_line(data, now, tz)
    return lines + [usage] if usage else lines


def main(stdin=sys.stdin, stdout=sys.stdout):
    try:
        try:
            data = json.loads(stdin.read() or '{}')
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        print('\n'.join(render(data)), file=stdout)
    except Exception as error:  # never blank the line: show what went wrong instead
        print(f'statusline: {error}', file=stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
