"""shell_reader: a shell command line in, its commands out.

worktree-guard (which folders a call changes, which worktree commands it runs) and small-commits
(which `git commit`s, with what message) both read a Bash call's command line through this one
reader, so both read it the same way. It lives in lib/ because that is what the features share.

    read(line) -> [Command(words, folder, heredocs), ...]

Each Command is one simple command, in the order the shell runs them: its words, quotes removed and
redirections left out; the folder it runs in, relative to the shell's own ('' for that one); and the
bodies of the heredocs it reads. The rules:

- A heredoc's text is never a command: its body goes to the command that reads it, not to the words.
- A newline ends a command, as `;` does; only a quote or a backslash keeps a line going.
- An unclosed quote is a plain character, so it never swallows the lines after it.
- A quote, `$(...)` included, is one word, even across lines: a commit message with blank lines
  and a `$(cat <<'EOF' ... EOF)` are each one word.
- Commands inside `$(...)`, `( ... )` and a shell's `-c '...'` come out too, where they run. A
  `cd` or `pushd` moves the folder of what follows it, except in a pipeline, in the background
  or in a subshell, where the shell is a copy; a subshell and a substitution leave no `cd` behind.
- Nothing raises, and the time is linear in the line (bar the rare unclosed quote). A line this
  does not understand reads as the words it holds.

`Command.argv` is the words from the program on, after `VAR=x`, keywords and wrappers like `sudo`.

Not read: `$'...'`, backticks, `<(...)`, `eval`, functions and aliases, and a shell fed a script
by a heredoc (`bash <<EOF`): that text is never a command, as the first rule says.

A scanner of its own, not shlex: shlex has no heredocs and no newlines, and raises on a stray
apostrophe, which is how a heredoc's text ended up read as commands (#82, #48).
Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

BLANKS = ' \t\r'
OPERATOR_CHARS = ';&|()'
REDIRECT_CHARS = '<>'
STOPS = BLANKS + '\n' + OPERATOR_CHARS + REDIRECT_CHARS
ESCAPED_IN_DOUBLE = '$`"\\\n'
ASSIGNMENT = re.compile(r'[A-Za-z_]\w*\+?=')
KEYWORDS = frozenset(('if', 'then', 'elif', 'else', 'do', 'while', 'until', '!', '{', '}'))
WRAPPERS = frozenset(('sudo', 'env', 'command', 'exec', 'time', 'nohup', 'nice', 'timeout', 'gtimeout'))
SHELLS = frozenset(('sh', 'bash', 'zsh', 'dash', 'ksh'))
SHELL_C = re.compile(r'-\w*c')  # -c, -lc, -ec ...
CHANGE_FOLDER = frozenset(('cd', 'pushd'))
PIPES = frozenset(('|', '|&', '&'))  # what runs the command before it in a subshell of its own


@dataclass(frozen=True)
class Command:
    words: tuple             # the command's words, quotes removed, redirections left out
    folder: str = ''         # where it runs, relative to the shell's own folder
    heredocs: tuple = ()     # the bodies of the heredocs it reads, in order

    @property
    def argv(self):
        """The words from the program on: after `VAR=x`, a keyword (`then`, `!`...) and a wrapper
        (`sudo`, `env`, `time`...)."""
        at = 0
        while at < len(self.words) and (ASSIGNMENT.match(self.words[at]) or self.words[at] in KEYWORDS
                                        or Path(self.words[at]).name in WRAPPERS):
            at += 1
        return self.words[at:]


class Reader:
    def __init__(self, text, folder=''):
        self.text, self.at, self.folder = text, 0, folder
        self.found = []     # [words, folder, the boxes of its heredocs]: a body is read after its command
        self.pending = []   # (terminator, box) for each heredoc opened on this line, in order
        self.unclosed = set()  # where a `$(` was found never to close, so that is learnt once

    def peek(self, offset=0):
        at = self.at + offset
        return self.text[at] if at < len(self.text) else ''

    def commands(self):
        self.block()
        return [Command(words, folder, tuple(box[0] for box in boxes)) for words, folder, boxes in self.found]

    def block(self, closing=False):
        """Read commands into self.found up to the end, or (when `closing`) up to the `)` that
        ends a subshell or a substitution. Whether it ended on that `)`."""
        words, boxes, redirect, piped = [], [], None, False
        while True:
            kind, value = self.token()
            if kind == 'word':
                if redirect in ('<<', '<<-'):  # the word after it is the terminator, not a word
                    boxes.append([''])
                    self.pending.append((value, boxes[-1]))
                elif redirect is None:
                    words.append(value)
                redirect = None
                continue
            if kind == 'redirect':
                redirect = value
                continue
            if words:
                self.add(tuple(words), boxes, moves=not piped and value not in PIPES)
            words, boxes, redirect, piped = [], [], None, value in ('|', '|&')
            if value == '\n':
                self.bodies()
            elif value == '(':
                folder, piped = self.folder, False
                self.block(closing=True)
                self.folder = folder
            elif value == ')' and closing:
                return True
            elif kind == 'end':
                return False

    def add(self, words, boxes, moves):
        """Keep a command that ran where the cursor is; then a `cd` moves the folder (when it is not
        in a pipeline or the background, whose shell is a copy), and a shell's script is read."""
        command = Command(words, self.folder)
        self.found.append([words, self.folder, boxes])
        argv = command.argv
        if argv[:1] and argv[0] in CHANGE_FOLDER and moves and argv[1:2] and not argv[1].startswith('-'):
            self.folder = os.path.join(self.folder, argv[1])
        if argv[:1] and Path(argv[0]).name in SHELLS:
            flag = next((n for n, word in enumerate(argv) if SHELL_C.fullmatch(word)), None)
            if flag is not None and flag + 1 < len(argv):
                self.found += [[c.words, c.folder, [[h] for h in c.heredocs]]
                               for c in Reader(argv[flag + 1], self.folder).commands()]

    def substitution(self):
        """Read a `$(...)` whose `$(` was just read: its commands join self.found, and the text
        from the `$(` to its `)` comes back. None, with the cursor after the `$`, when it never
        closes: the `$` is a character, and the `(` after it starts a subshell."""
        start = self.at - 2
        if start in self.unclosed:
            self.at = start + 1
            return None
        found, pending, folder = len(self.found), self.pending, self.folder
        self.pending = []
        closed = self.block(closing=True)
        self.pending, self.folder = pending, folder
        if closed:
            return self.text[start:self.at]
        del self.found[found:]
        self.unclosed.add(start)
        self.at = start + 1
        return None

    def bodies(self):
        """Read the bodies of the heredocs the line just ended opened: each runs to a line that is
        its terminator, or to the end."""
        lines = self.text[self.at:].split('\n')
        taken = 0
        for terminator, box in self.pending:
            body = []
            while taken < len(lines):
                line = lines[taken]
                taken += 1
                if line.strip() == terminator:
                    break
                body.append(line)
            box[0] = ''.join(line + '\n' for line in body)
        self.at += sum(len(line) + 1 for line in lines[:taken])
        self.at = min(self.at, len(self.text))
        self.pending = []

    def token(self):
        """(kind, value) of the next token: a 'word', a 'redirect', an 'operator' (`;`, `&&`, `|`,
        a newline...), or 'end'."""
        while self.peek() in tuple(BLANKS) or self.text.startswith('\\\n', self.at):
            self.at += 2 if self.peek() == '\\' else 1
        char = self.peek()
        if not char:
            return 'end', ''
        if char == '#':
            while self.peek() not in ('', '\n'):
                self.at += 1
            return self.token()
        if char == '\n' or char in OPERATOR_CHARS:
            if char == '&' and self.peek(1) == '>':  # &> and &>>
                self.at += 3 if self.peek(2) == '>' else 2
                return 'redirect', '>'
            start = self.at
            self.at += 1
            if char in '&|;' and self.peek() in (char, '&' if char == '|' else char):
                self.at += 1
            return 'operator', self.text[start:self.at]
        if char in REDIRECT_CHARS:
            return 'redirect', self.redirect()
        word, plain = self.word()
        if plain and word.isdigit() and self.peek() in tuple(REDIRECT_CHARS):  # the 2 of 2>&1
            return 'redirect', self.redirect()
        return 'word', word

    def redirect(self):
        """Read a redirection's operator, at a `<` or `>`."""
        for operator in ('<<<', '<<-', '<<', '<>', '<&', '<', '>>', '>&', '>|', '>'):
            if self.text.startswith(operator, self.at):
                self.at += len(operator)
                return operator
        raise AssertionError('not at a redirection')

    def word(self):
        """(the word at the cursor with its quotes removed, whether none were used)."""
        out, plain = [], True
        while True:
            char = self.peek()
            if not char or char in STOPS:
                return ''.join(out), plain
            self.at += 1
            if char == '\\':
                escaped = self.peek()
                self.at += 1 if escaped else 0
                if escaped != '\n':  # a backslash and a newline join the lines
                    out.append(escaped or char)
            elif char in '\'"':
                inside = self.quoted(char)
                if inside is None:
                    out.append(char)  # never closed: just a character
                else:
                    out.append(inside)
                    plain = False
            elif char == '$' and self.peek() == '(':
                self.at += 1
                out.append(self.substitution() or char)
                plain = False
            else:
                out.append(char)

    def quoted(self, quote):
        """The text of the quote whose opening mark was just read, or None when it never closes
        (the cursor stays where it was)."""
        start, out, found = self.at, [], len(self.found)
        while self.at < len(self.text):
            char = self.text[self.at]
            self.at += 1
            if char == quote:
                return ''.join(out)
            if char == '\\' and quote == '"' and self.peek() in tuple(ESCAPED_IN_DOUBLE) and self.peek():
                if self.peek() != '\n':
                    out.append(self.peek())
                self.at += 1
            elif char == '$' and quote == '"' and self.peek() == '(':  # its own quotes and lines are its own
                self.at += 1
                out.append(self.substitution() or char)
            else:
                out.append(char)
        self.at = start
        del self.found[found:]  # what its substitutions read is read again, without the quote
        return None


def read(line, folder=''):
    """The commands a shell command line runs, in order (see the module's docstring)."""
    return Reader(line, folder).commands()
