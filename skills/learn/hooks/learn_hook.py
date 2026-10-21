#!/usr/bin/env python3
"""Mark possible learning moments for the `learn` skill in Claude Code, Codex, Antigravity, and Pi.

  learn_hook.py prompt --cli CLI   user prompt: snapshot plan statuses once per session,
                                   and add context when the prompt holds a learning cue
  learn_hook.py stop --cli CLI     end of turn: continue once when a plan turned `done`

Reads the CLI's hook JSON on stdin and prints that CLI's reply, or nothing. The session's
own model decides whether a moment is worth a review. State lives in
~/.local/state/ai-dotfiles/learn/, one file per session, deleted after 7 days. Any error
exits 0 without output, so a broken hook never blocks a session. Python 3.9+, stdlib only.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

KEYWORDS = Path(__file__).resolve().parents[1] / 'keywords.txt'
STATE = Path.home() / '.local/state/ai-dotfiles/learn'
CLIS = ('claude', 'codex', 'agy', 'pi')
MAX_ASKS = 3
KEEP_SECONDS = 7 * 24 * 3600

PROMPT_NOTE = (
    'The user prompt contains the learning cue "{cue}". The `learn` skill reviews the agent '
    'setup (rules, skills, hooks) after a mistake and proposes the smallest fix. Decide whether '
    'this prompt reports such a mistake; if it does, use the `learn` skill once the request is '
    'handled. If it does not, carry on as usual.')
STOP_NOTE = (
    'Plan {plans} was marked done in this session. Decide whether the work held a mistake or '
    'a lesson about the agent setup. If yes, use the `learn` skill now. If not, say so in one '
    'line and stop.')


def load_keywords(path=KEYWORDS):
    phrases = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            phrases.append(normalize(line))
    return phrases


def normalize(text):
    return ' '.join(text.replace('’', "'").lower().split())


def find_cue(prompt, phrases):
    """The first phrase in the prompt; pasted blocks are ignored, English needs whole words."""
    text = normalize(re.sub(r'<pasted_content[^>]*>.*?</pasted_content[^>]*>', ' ', prompt, flags=re.S))
    for phrase in phrases:
        if phrase.isascii():
            if re.search(rf'(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])', text):
                return phrase
        elif phrase in text:
            return phrase
    return None


def repo_root(path):
    start = Path(path).resolve()
    for folder in (start, *start.parents):
        if (folder / '.git').exists():
            return folder
    return start


def status_of(path):
    """First word of the first `Status:` line, with Markdown bold removed."""
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    for line in text.splitlines():
        if line.lower().startswith('status:'):
            words = line[len('status:'):].replace('*', '').split()
            return words[0].strip('.,;:()').lower() if words else ''
    return ''


def plan_statuses(root):
    folder = Path(root) / 'docs/plans'
    if not folder.is_dir():
        return {}
    return {path.name: status_of(path) for path in sorted(folder.glob('*.md'))}


def session_of(cli, data):
    """(session id, workspace folder) from the CLI's hook input."""
    if cli == 'agy':
        paths = data.get('workspacePaths') or []
        return data.get('conversationId'), (paths[0] if paths else None)
    return data.get('session_id'), data.get('cwd')


def agy_prompt(data, state):
    """Latest user request from Antigravity's transcript, once per turn (it has no prompt field)."""
    path = data.get('transcriptPath')
    if not path or not Path(path).is_file():
        return ''
    last = None
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            step = json.loads(line)
        except ValueError:
            continue
        if isinstance(step, dict) and step.get('type') == 'USER_INPUT':
            last = step
    if last is None or last.get('step_index') == state.get('agy_step'):
        return ''
    state['agy_step'] = last.get('step_index')
    content = str(last.get('content') or '')
    match = re.search(r'<USER_REQUEST>(.*?)</USER_REQUEST>', content, flags=re.S)
    return match.group(1) if match else content


def context(cli, text):
    if cli == 'agy':
        return {'injectSteps': [{'ephemeralMessage': text}]}
    if cli == 'pi':
        return {'context': text}
    return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}}


def proceed(cli, text):
    if cli == 'claude':
        return {'hookSpecificOutput': {'hookEventName': 'Stop', 'additionalContext': text}}
    if cli == 'codex':
        return {'decision': 'block', 'reason': text}
    if cli == 'agy':
        return {'decision': 'continue', 'reason': text}
    return {'continue': text}


def quiet(cli, mode):
    """The no-op reply: Codex wants JSON from Stop, Antigravity wants a decision."""
    if mode == 'stop' and cli == 'codex':
        return {}
    if mode == 'stop' and cli == 'agy':
        return {'decision': 'stop'}
    return None


def on_prompt(cli, data, state, phrases):
    if 'plans' not in state:
        root = repo_root(session_of(cli, data)[1] or os.getcwd())
        state['root'] = str(root)
        state['plans'] = plan_statuses(root)
    prompt = agy_prompt(data, state) if cli == 'agy' else str(data.get('prompt') or '')
    cue = find_cue(prompt, phrases) if prompt else None
    return context(cli, PROMPT_NOTE.format(cue=cue)) if cue else None


def on_stop(cli, data, state):
    if data.get('stop_hook_active'):
        return None
    if state.pop('pending', False):  # the turn our own continuation started (Antigravity, Pi)
        return None
    if 'plans' not in state or state.get('asks', 0) >= MAX_ASKS:
        return None
    asked = state.setdefault('asked', [])
    done = [name for name, status in plan_statuses(state['root']).items()
            if status == 'done' and state['plans'].get(name) != 'done' and name not in asked]
    if not done:
        return None
    asked.extend(done)
    state['asks'] = state.get('asks', 0) + 1
    if cli in ('agy', 'pi'):
        state['pending'] = True
    return proceed(cli, STOP_NOTE.format(plans=', '.join(f'docs/plans/{name}' for name in done)))


def state_file(state_dir, cli, session):
    return Path(state_dir) / f"{cli}-{re.sub(r'[^A-Za-z0-9_.-]', '_', str(session))[:128]}.json"


def load_state(path):
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        json.dump(state, f, ensure_ascii=False, sort_keys=True)
    os.chmod(f.name, 0o600)
    os.replace(f.name, path)


def prune(state_dir, now):
    for path in Path(state_dir).glob('*.json'):
        try:
            if now - path.stat().st_mtime > KEEP_SECONDS:
                path.unlink()
        except OSError:
            pass


def run(mode, cli, data, state_dir=STATE, phrases=None, now=None):
    """The reply for one hook call, or None; state is read and written around it."""
    session = session_of(cli, data)[0]
    if not session:
        return quiet(cli, mode)
    prune(state_dir, time.time() if now is None else now)
    path = state_file(state_dir, cli, session)
    state = load_state(path)
    if mode == 'prompt':
        reply = on_prompt(cli, data, state, load_keywords() if phrases is None else phrases)
    else:
        reply = on_stop(cli, data, state)
    save_state(path, state)
    return reply if reply is not None else quiet(cli, mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('prompt', 'stop'))
    parser.add_argument('--cli', choices=CLIS, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:  # exit 2 would block the prompt or continue the turn
        return 0
    try:
        data = json.loads(sys.stdin.read() or '{}')
        reply = run(args.mode, args.cli, data if isinstance(data, dict) else {})
    except Exception:  # never block the session over a hook problem
        reply = quiet(args.cli, args.mode)
    if reply is not None:
        print(json.dumps(reply, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
