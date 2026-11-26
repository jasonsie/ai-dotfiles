"""agent_sessions: one interface over the session stores of Claude Code, Codex and Pi.

A daily pass sees plain Sessions: the prompts, replies and edited files of every transcript
that has a turn in a time window. This module finds each CLI's transcripts, keeps the lines
inside the window and leaves out what is not the user's own work (subagent threads, injected
context, sessions in scratch folders). Where each CLI keeps its transcripts and how its lines read is
its adapter's (lib/adapters); the windows, the Session and the filtering are the same for all.

  window(day, cutoff_hour, tz)    [day at cutoff_hour, the next day at cutoff_hour) in local time
  sessions(start, end, home)      every Session with a turn in [start, end), oldest first
  read(cli, path, start, end)     one transcript's Session, or None
  last_reply(cli, path)           the agent's last message in one transcript, from the file's tail
  note_since_prompt(cli, path, p) whether the harness left a note starting with p after the last prompt
  is_temp(cwd)                    a scratch folder; sessions() drops the sessions that ran in one

A Session's turns and files hold only what falls inside the window; its title and cwd belong to
the whole transcript. A file or line that cannot be read is skipped, never raised. Every file of a
store is listed (Codex names its day folders by the LOCAL day a session began and a resumed session
keeps writing there), and each file's modification time rules the old ones out. A resumed or forked session replays its parent's lines (Claude Code's
continued-in, Pi's parentSession), so one turn can show up in two Sessions; telling them apart is
the caller's job. Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import adapters  # noqa: E402  (each CLI's session store: where it keeps transcripts and how its lines read)

CLIS = tuple(cli for cli in adapters.CLIS if adapters.get(cli).session_store)
TEMP_PREFIXES = ('/tmp/', '/private/tmp/', '/var/folders/', '/private/var/folders/')
TITLE_MAX = 80
ALWAYS = (datetime.min.replace(tzinfo=timezone.utc), datetime.max.replace(tzinfo=timezone.utc))  # a window with no edges


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
        for path in _transcripts(cli, home / adapters.get(cli).session_store):
            session = read(cli, path, start, end) if _written_since(path, start) else None
            if session and not is_temp(session.cwd):
                found.append(session)
    return sorted(found, key=lambda session: (session.started, session.cli, session.id))


def read(cli: str, path: Path, start: datetime, end: datetime) -> Session | None:
    """The Session in one transcript, or None: nothing in [start, end), a subagent's thread, an
    unknown `cli`, or a file that cannot be read. A line that is not JSON, or not shaped like
    the store's lines, is skipped."""
    handle = _row_reader(cli)
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
    handle = _row_reader(cli)
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
    adapter = adapters.get(cli)
    return adapter.leaves_notes and adapter.note_since_prompt(_tail(path, tail), prefix)


def _row_reader(cli):
    """What reads the lines of `cli`'s transcripts, or None when it keeps none."""
    adapter = adapters.get(cli)
    return adapter.read_row if adapter.session_store else None


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
    the old ones closed)."""
    try:
        return adapters.get(cli).transcripts(store)
    except OSError:
        return []


def _written_since(path, start):
    try:
        return path.stat().st_mtime >= start.timestamp()
    except OSError:
        return False


# --- one transcript ----------------------------------------------------------------------

def _clean(texts):
    """The texts that say something, stripped."""
    return [text.strip() for text in texts if isinstance(text, str) and text.strip()]


class _Reader:
    """What the lines of one transcript have said so far."""

    def __init__(self, cli, path, start, end):
        self.cli, self.path, self.start, self.end = cli, path, start, end
        self.id, self.cwd = adapters.get(cli).session_id(path.stem), ''
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
