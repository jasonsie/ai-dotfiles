#!/usr/bin/env python3
"""Migrate legacy local CLI settings; dry-run unless --apply. Never reads auth files.

Preserves unrelated keys and model choices (except Pi's out-of-scope default).
Backs up all affected files privately before writing; rolls back on failure.
Global instruction links are handled by install-global-instructions.py.
Requires Python 3.11+ for TOML validation.
"""
import argparse
import copy
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib

EVENTS = {
    'session-start': 'SessionStart', 'user-prompt': 'BeforeAgent',
    'pre-tool': 'BeforeTool', 'post-tool': 'AfterTool', 'session-end': 'SessionEnd',
}


def migrate_json(kind, original):
    data = copy.deepcopy(original)
    if kind == 'gemini':
        if isinstance(data.get('model'), str):
            data['model'] = {'name': data['model']}
        if 'theme' in data:
            theme = data.pop('theme')
            data.setdefault('ui', {}).setdefault('theme', 'Default' if theme == 'default' else theme)
        data.pop('sandbox', None)
        data.setdefault('tools', {})['sandbox'] = True
        data['tools'].pop('approvalMode', None)
        data.setdefault('general', {})['defaultApprovalMode'] = 'default'
        hooks = data.get('hooks', {})
        migrated = False
        for old, new in EVENTS.items():
            if old not in hooks:
                continue
            entries = hooks.pop(old)
            for entry in entries:
                if 'command' in entry:
                    entry['hooks'] = [{'name': 'workspace-' + old, 'type': 'command',
                                       'command': entry.pop('command')}]
                if old == 'pre-tool':
                    entry['matcher'] = 'run_shell_command'
                elif old == 'post-tool':
                    entry['matcher'] = 'write_file|replace'
            hooks.setdefault(new, []).extend(entries)
            migrated = True
        if migrated:
            # Old workspace scripts have not passed Gemini hook I/O tests.
            # Disable only migrated hooks, not unrelated user hooks.
            disabled = data.setdefault('hooksConfig', {}).setdefault('disabled', [])
            for old in EVENTS:
                name = 'workspace-' + old
                if name not in disabled:
                    disabled.append(name)
    elif kind == 'pi':
        provider = data.get('defaultProvider', '')
        model = data.get('defaultModel', '')
        patterns = data.get('enabledModels', [])
        if patterns and not any(fnmatch.fnmatch(f'{provider}/{model}', p) or
                                fnmatch.fnmatch(model, p) for p in patterns):
            candidates = [p.split('/', 1)[1] for p in patterns
                          if p.startswith(provider + '/') and not any(c in p for c in '*?[')]
            if not candidates:
                raise ValueError('Pi has no exact enabled model for its default provider')
            data['defaultModel'] = candidates[0]
    elif kind == 'claude':
        data['skipDangerousModePermissionPrompt'] = False
        data['skipAutoPermissionPrompt'] = False
        if data.get('permissions', {}).get('defaultMode') in ('bypassPermissions', 'auto'):
            data['permissions']['defaultMode'] = 'default'
    return data


def migrate_codex(text, home):
    tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    first_table = next((i for i, line in enumerate(lines) if line.lstrip().startswith('[')), len(lines))
    header = ''.join(lines[:first_table])
    rest = ''.join(lines[first_table:])
    header = re.sub(r'(?m)^(approval_mode|sandbox|approval_policy|sandbox_mode)\s*=.*\n?', '', header)
    header = header.rstrip() + '\napproval_policy = "on-request"\nsandbox_mode = "workspace-write"\n\n'
    text = header + rest
    # Remove blanket home trust, retaining specific repository trust entries.
    table = '[projects.' + json.dumps(str(home)) + ']'
    pattern = r'(?m)^' + re.escape(table) + r'\s*\n(?:(?!^\[)[\s\S])*'
    text = re.sub(pattern, '', text)
    tomllib.loads(text)
    return text


def plan(home):
    changes = []
    for kind, relative in (
        ('claude', '.claude/settings.json'), ('pi', '.pi/agent/settings.json'),
        ('gemini', '.gemini/settings.json'), ('codex', '.codex/config.toml'),
    ):
        path = home / relative
        if path.is_symlink():
            raise ValueError(f'Refusing to replace symlinked settings: {path}')
        if not path.exists():
            continue
        before = path.read_bytes()
        text = before.decode()
        if kind == 'codex':
            after = migrate_codex(text, home).encode()
        else:
            original = json.loads(text)
            migrated = migrate_json(kind, original)
            after = before if migrated == original else (json.dumps(migrated, indent=2) + '\n').encode()
        if before != after:
            changes.append((path, before, after))
    return changes


def atomic_write(path, content, mode):
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temp = Path(directory) / 'settings'
        temp.write_bytes(content)
        temp.chmod(mode)
        os.replace(temp, path)


def apply(home, changes):
    root = home / '.local/state/ai-cli-workspace/config-repair'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='backup-', dir=root))
    for path, before, _ in changes:
        if path.is_symlink() or path.read_bytes() != before:
            raise ValueError(f'Concurrent edit detected: {path}')
        saved = backup / path.relative_to(home)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
    done = []
    try:
        for path, before, after in changes:
            if path.is_symlink() or path.read_bytes() != before:
                raise ValueError(f'Concurrent edit detected: {path}')
            mode = path.stat().st_mode & 0o777
            done.append((path, before, mode))
            atomic_write(path, after, mode)
    except BaseException:
        for path, before, mode in reversed(done):
            atomic_write(path, before, mode)
        raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    changes = plan(home)
    for path, _, _ in changes:
        print(f'{"Repair" if args.apply else "Would repair"}: {path}')
    if args.apply and changes:
        print(f'Backup: {apply(home, changes)}')
    print(f'{len(changes)} changes')


if __name__ == '__main__':
    main()
