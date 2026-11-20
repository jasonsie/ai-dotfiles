"""agent_sessions: one interface over the session stores of Claude Code, Codex and Pi.

A daily pass sees plain Sessions: the prompts, replies and edited files of every transcript
that has a turn in a time window. This module finds each CLI's transcripts, keeps the lines
inside the window and leaves out what is not the user's own work (subagent threads, injected
context, sessions in scratch folders). Everything that differs between the stores lives here.

  window(day, cutoff_hour, tz)    [day at cutoff_hour, the next day at cutoff_hour) in local time
  sessions(start, end, home)      every Session with a turn in [start, end), oldest first
  read(cli, path, start, end)     one transcript's Session, or None
  last_reply(cli, path)           the agent's last message in one transcript, from the file's tail
  note_since_prompt(cli, path, p) whether the harness left a note starting with p after the last prompt
  is_temp(cwd)                    a scratch folder; sessions() drops the sessions that ran in one

A Session's turns and files hold only what falls inside the window; its title and cwd belong to
the whole transcript. A file or line that cannot be read is skipped, never raised. Codex names
its day folders by the LOCAL day a session began (not the UTC day) and a resumed session keeps
writing there, so every folder is listed and each file's modification time, not its folder's date,
rules the old ones out. A resumed or forked session replays its parent's lines (Claude Code's
continued-in, Pi's parentSession), so one turn can show up in two Sessions; telling them apart is
the caller's job. Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re

CLIS = ('claude', 'codex', 'pi')
TEMP_PREFIXES = ('/tmp/', '/private/tmp/', '/var/folders/', '/private/var/folders/')
STORES = {  # relative to home
    'claude': '.claude/projects',        # <store>/<cwd-slug>/<session-id>.jsonl
    'codex': '.codex/sessions',          # <store>/YYYY/MM/DD/rollout-<ts>-<id>.jsonl, a folder per local day
    'pi': '.pi/agent/sessions',          # <store>/<cwd-slug>/<ts>_<id>.jsonl
}
TITLE_MAX = 80
EDIT_TOOLS = {'claude': {'Edit', 'Write', 'NotebookEdit'}, 'pi': {'edit', 'write'}}
# Claude Code lines that look like turns but are not: injected, a subagent's, a summary, an API error.
NOT_A_TURN = ('isMeta', 'isSidechain', 'isCompactSummary', 'isApiErrorMessage')
ALWAYS = (datetime.min.replace(tzinfo=timezone.utc), datetime.max.replace(tzinfo=timezone.utc))  # a window with no edges
ROLLOUT = re.compile(r'rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-(.+)')
PATCH_FILE = re.compile(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', re.MULTILINE)


@dataclass(frozen=True)
class Turn:
    at: datetime        # timezone-aware
    role: str           # 'user' or 'assistant'
    text: str


@dataclass
class Session:
    cli: str
    id: str
    cwd: str
    title: str          # Claude: the last ai-title; else the first prompt's first line, at most TITLE_MAX
    started: datetime   # first turn in the window
    ended: datetime     # last turn in the window
    turns: list[Turn]   # user prompts and assistant texts inside the window, in order
    files: tuple[str, ...]   # paths edited inside the window, sorted, unique
    path: Path          # the transcript file


def window(day: date, cutoff_hour: int = 4, tz=None) -> tuple[datetime, datetime]:
    """[day at cutoff_hour, the next day at cutoff_hour) as aware datetimes. `tz` None is the
    system zone, with the offset it had on each of those mornings (daylight saving stays right)."""
    def morning(d):
        local = datetime.combine(d, time(cutoff_hour))
        return local.astimezone() if tz is None else local.replace(tzinfo=tz)
    return morning(day), morning(day + timedelta(days=1))


def is_temp(cwd: str) -> bool:
    """Whether `cwd` is a scratch folder: one of TEMP_PREFIXES, or inside one. The string is
    judged as written (and normalized); the disk is never asked."""
    if not isinstance(cwd, str) or not cwd:
        return False
    return any(form == prefix.rstrip('/') or form.startswith(prefix)
               for form in (cwd, os.path.normpath(cwd)) for prefix in TEMP_PREFIXES)


def sessions(start: datetime, end: datetime, home: Path | None = None) -> list[Session]:
    """Every session of every CLI with a turn in [start, end), by start time, less those that ran
    in a scratch folder. A missing store, and a file that cannot be read, is skipped; a file last
    written before `start` is not even opened, which is what keeps a store of many days cheap."""
    start, end = _aware(start), _aware(end)
    home = Path(home) if home is not None else Path.home()
    found = []
    for cli in CLIS:
        for path in _transcripts(cli, home / STORES[cli]):
            session = read(cli, path, start, end) if _written_since(path, start) else None
            if session and not is_temp(session.cwd):
                found.append(session)
    return sorted(found, key=lambda session: (session.started, session.cli, session.id))


def read(cli: str, path: Path, start: datetime, end: datetime) -> Session | None:
    """The Session in one transcript, or None: nothing in [start, end), a subagent's thread, an
    unknown `cli`, or a file that cannot be read. A line that is not JSON, or not shaped like
    the store's lines, is skipped."""
    handle = READERS.get(cli)
    if handle is None:
        return None
    path = Path(path)
    reader = _Reader(cli, path, _aware(start), _aware(end))
    try:
        with open(path, encoding='utf-8', errors='replace') as lines:
            for line in lines:
                _feed(handle, reader, line)
    except (OSError, ValueError):  # ValueError: a path with a NUL in it
        return None
    return reader.session()


def last_reply(cli: str, path, tail: int = 256 * 1024) -> str:
    """The agent's last message to the user in one transcript: the text of its last assistant
    turn, found in the file's last `tail` bytes so that a long session stays cheap. '' when
    that tail holds none, the file cannot be read, or `cli` is unknown."""
    handle = READERS.get(cli)
    if handle is None:
        return ''
    reader = _Reader(cli, Path(path), *ALWAYS)
    for line in _tail(path, tail):
        _feed(handle, reader, line)
    replies = sorted((turn for turn in reader.turns if turn.role == 'assistant'), key=lambda turn: turn.at)
    return replies[-1].text if replies else ''


def note_since_prompt(cli: str, path, prefix: str, tail: int = 256 * 1024) -> bool:
    """Whether Claude Code's harness left a note starting with `prefix` (one of its meta rows, such
    as the usage-limit note) after the last prompt of one transcript, in the file's last `tail`
    bytes. False for the other stores, and for a file that cannot be read."""
    if cli != 'claude':
        return False
    found = False
    for line in _tail(path, tail):
        try:
            row = _obj(json.loads(line))
        except ValueError:
            continue
        if row.get('type') != 'user' or row.get('isSidechain'):
            continue
        content = _obj(row.get('message')).get('content')
        if row.get('isMeta'):
            texts = [content] if isinstance(content, str) else [b.get('text') for b in map(_obj, _items(content))]
            found = found or any(_text(text).startswith(prefix) for text in texts)
        elif isinstance(content, str) and content.strip():  # a new prompt: notes before it no longer count
            found = False
    return found


def _tail(path, size):
    """The whole lines in a file's last `size` bytes, or none when it cannot be read."""
    try:
        with open(path, 'rb') as file:
            start = max(0, file.seek(0, os.SEEK_END) - size)
            file.seek(start)
            lines = file.read().decode('utf-8', errors='replace').splitlines()
    except (OSError, ValueError):
        return []
    return lines[1 if start else 0:]  # a tail that starts inside the file starts inside a line


def _feed(handle, reader, line):
    """Give one line of a transcript to its store's reader; a line that is not JSON, or not
    shaped like the store's lines, is skipped."""
    try:
        row = json.loads(line)
        if isinstance(row, dict):
            handle(reader, row)
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError):
        pass


def _aware(moment):
    """`moment` as it is, or as local time when it is naive."""
    return moment if moment.tzinfo else moment.astimezone()


def _transcripts(cli, store):
    """The transcript files of one CLI: every file of the store (the mtime check in sessions() keeps
    the old ones closed). Codex files sit under the day the session began, and a session resumed
    days later keeps writing there, so no day folder is skipped."""
    try:
        if cli == 'codex':
            return sorted(store.glob('*/*/*/*.jsonl'))
        return sorted(store.glob('*/*.jsonl'))  # not deeper: Claude Code keeps subagent threads there
    except OSError:
        return []


def _written_since(path, start):
    try:
        return path.stat().st_mtime >= start.timestamp()
    except OSError:
        return False


# --- one transcript ----------------------------------------------------------------------

def _when(value):
    """The aware datetime in an ISO 8601 string (the stores write UTC), or None."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _obj(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    """The dicts in a list."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value):
    return value if isinstance(value, str) else ''


def _args(value):
    """A tool call's arguments as a dict: given as one, or as a JSON string; else empty."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return _obj(value)


def _clean(texts):
    """The texts that say something, stripped."""
    return [text.strip() for text in texts if isinstance(text, str) and text.strip()]


class _Reader:
    """What the lines of one transcript have said so far."""

    def __init__(self, cli, path, start, end):
        self.cli, self.path, self.start, self.end = cli, path, start, end
        self.id, self.cwd = _file_id(cli, path.stem), ''
        self.ai_title = self.first_prompt = ''
        self.opened = False      # Codex: the first session_meta has been read
        self.subagent = False    # a thread an agent started for another agent, not the user's own
        self.turns, self.edits = [], set()

    def user(self, at, texts, hidden=('<',)):
        """A prompt: `texts` less those that start like injected context (`hidden`)."""
        text = '\n'.join(part for part in _clean(texts) if not part.startswith(hidden))
        if text:
            self.first_prompt = self.first_prompt or text.splitlines()[0].strip()[:TITLE_MAX]
            self.say(at, 'user', text)

    def assistant(self, at, texts):
        text = '\n'.join(_clean(texts))
        if text:
            self.say(at, 'assistant', text)

    def say(self, at, role, text):
        if self.start <= at < self.end:
            self.turns.append(Turn(at, role, text))

    def edited(self, at, path):
        if isinstance(path, str) and path and self.start <= at < self.end:
            self.edits.add(path)

    def session(self):
        if self.subagent or not self.turns:
            return None
        turns = sorted(self.turns, key=lambda turn: turn.at)
        files = tuple(sorted({os.path.normpath(os.path.join(self.cwd, path)) for path in self.edits}))
        return Session(self.cli, self.id, self.cwd, self.ai_title or self.first_prompt,
                       turns[0].at, turns[-1].at, turns, files, self.path)


def _file_id(cli, stem):
    """A session's id from its file name, until the transcript says it itself."""
    if cli == 'codex':
        named = ROLLOUT.fullmatch(stem)
        return named.group(1) if named else stem
    if cli == 'pi':
        return stem.split('_', 1)[-1]
    return stem


# --- one reader per store ----------------------------------------------------------------
# Each is given the lines of a transcript, as dicts, and tells the _Reader what they say. Only
# turns and edits need a timestamp; ids, titles and folders sit on lines that have none.

def _claude(reader, row):
    kind = row.get('type')
    if kind == 'ai-title':  # no timestamp, and it may come again: the last one is the title
        reader.ai_title = _text(row.get('aiTitle')).strip() or reader.ai_title
        return
    reader.cwd = reader.cwd or _text(row.get('cwd'))
    at = _when(row.get('timestamp'))
    if kind not in ('user', 'assistant') or at is None or any(row.get(flag) for flag in NOT_A_TURN):
        return
    content = _obj(row.get('message')).get('content')
    if kind == 'user':  # a list is tool results, not a prompt
        if isinstance(content, str):
            reader.user(at, [content])
        return
    blocks = _items(content)
    reader.assistant(at, [block.get('text') for block in blocks if block.get('type') == 'text'])
    for block in blocks:
        if block.get('type') == 'tool_use' and block.get('name') in EDIT_TOOLS['claude']:
            edit = _obj(block.get('input'))
            reader.edited(at, edit.get('file_path') or edit.get('notebook_path'))


def _codex(reader, row):
    kind, payload = row.get('type'), _obj(row.get('payload'))
    if kind == 'session_meta':
        if not reader.opened:  # a forked thread repeats its parent's meta after its own
            reader.opened = True
            reader.id = _text(payload.get('id')) or reader.id
            reader.cwd = _text(payload.get('cwd'))
            source = payload.get('source')
            reader.subagent = payload.get('thread_source') == 'subagent' or (
                isinstance(source, dict) and 'subagent' in source)
        return
    at = _when(row.get('timestamp'))
    if kind != 'response_item' or at is None:
        return
    item = payload.get('type')
    if item == 'message':
        texts = [part.get('text') for part in _items(payload.get('content'))
                 if part.get('type') in ('input_text', 'output_text')]
        if payload.get('role') == 'user':  # the injected AGENTS.md starts with '#'
            reader.user(at, texts, hidden=('<', '#'))
        elif payload.get('role') == 'assistant':
            reader.assistant(at, texts)
    elif item in ('custom_tool_call', 'function_call'):
        text = payload.get('input' if item == 'custom_tool_call' else 'arguments')
        for path in _patched(payload.get('name'), text):
            reader.edited(at, path)


def _patched(name, text):
    """The paths a Codex tool call edits, from the patch in its text, whatever the call is named.
    apply_patch carries the patch as its input, or as the `input` of JSON arguments. Any other
    call (exec runs JavaScript that calls apply_patch; a shell call may too) carries it inside a
    string, with the newlines escaped, so those are unescaped first. Only a line that starts with
    a directive counts, not a '+' line of a hunk that happens to quote one."""
    if not isinstance(text, str):
        return []
    if name == 'apply_patch':
        text = _text(_args(text).get('input')) or text
    return [path.strip() for path in PATCH_FILE.findall(text.replace('\\n', '\n')) if path.strip()]


def _pi(reader, row):
    kind = row.get('type')
    if kind == 'session':
        reader.id = _text(row.get('id')) or reader.id
        reader.cwd = _text(row.get('cwd'))
        return
    at = _when(row.get('timestamp'))
    if kind != 'message' or at is None:
        return
    message = _obj(row.get('message'))
    content = message.get('content')
    parts = _items(content)
    texts = [content] if isinstance(content, str) else [part.get('text') for part in parts
                                                        if part.get('type') == 'text']
    if message.get('role') == 'user':
        reader.user(at, texts)
    elif message.get('role') == 'assistant':
        reader.assistant(at, texts)
        for part in parts:
            if part.get('type') == 'toolCall' and part.get('name') in EDIT_TOOLS['pi']:
                reader.edited(at, _args(part.get('arguments')).get('path'))


READERS = {'claude': _claude, 'codex': _codex, 'pi': _pi}
