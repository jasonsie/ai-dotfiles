"""shell_reader: a shell command line in, its commands out (lib/shell_reader.py).

The reader worktree-guard and small-commits share. What is read: each command's words, the folder it
runs in, and the heredoc bodies it reads.

Run: python3 -m unittest discover -s scripts/tests -p 'test_shell_reader.py' -v
"""
import random
import sys
import time
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
import shell_reader  # noqa: E402


def words(line):
    return [command.words for command in shell_reader.read(line)]


class WordsTest(unittest.TestCase):
    def test_each_command_comes_out_with_its_words(self):
        self.assertEqual(words('git add -A && git commit -m "a b" ; ls | wc || true & echo'),
                         [('git', 'add', '-A'), ('git', 'commit', '-m', 'a b'), ('ls',), ('wc',), ('true',), ('echo',)])
        self.assertEqual(words(''), [])
        self.assertEqual(words('  ;; && '), [])

    def test_a_newline_ends_a_command_and_a_backslash_newline_does_not(self):
        self.assertEqual(words('ls\ngit status\n\n'), [('ls',), ('git', 'status')])
        self.assertEqual(words('git commit \\\n  -m x'), [('git', 'commit', '-m', 'x')])

    def test_quotes_make_one_word_even_across_lines(self):
        self.assertEqual(words("git commit -m 'subject\n\nbody; | && more'"),
                         [('git', 'commit', '-m', 'subject\n\nbody; | && more')])
        self.assertEqual(words('echo "say \\"hi\\" \\n" \'c d\' e" "f x\\ y'), [('echo', 'say "hi" \\n', 'c d', 'e f', 'x y')])
        self.assertEqual(words('echo ""'), [('echo', '')])

    def test_a_redirection_is_not_a_word_nor_is_its_target(self):
        self.assertEqual(words('git commit -m x 2>&1 > out.txt >> log <in &>all'), [('git', 'commit', '-m', 'x')])
        self.assertEqual(words('echo 2 > f; echo 2>f'), [('echo', '2'), ('echo',)])

    def test_a_comment_runs_to_the_end_of_its_line(self):
        self.assertEqual(words('ls # git commit && rm\ngit status'), [('ls',), ('git', 'status')])
        self.assertEqual(words('echo a#b "#c"'), [('echo', 'a#b', '#c')])


class HeredocTest(unittest.TestCase):
    def test_a_heredocs_text_goes_to_the_command_that_reads_it_and_is_never_a_command(self):
        cat, status = shell_reader.read("cat > f <<'EOF'\nrow | git commit -m x; rm -rf y\nEOF\ngit status")
        self.assertEqual((cat.words, cat.heredocs), (('cat',), ('row | git commit -m x; rm -rf y\n',)))
        self.assertEqual((status.words, status.heredocs), (('git', 'status'), ()))

    def test_the_ways_to_write_a_heredoc(self):
        for opener, terminator in (('<<EOF', 'EOF'), ('<< EOF', 'EOF'), ('<<"EOF"', 'EOF'), ('<<-EOF', '\tEOF'),
                                   ("<<'a b'", 'a b')):
            (command,) = shell_reader.read(f'cat {opener}\nx\n  y\n{terminator}\n')
            self.assertEqual((command.words, command.heredocs), (('cat',), ('x\n  y\n',)), opener)

    def test_what_follows_the_opener_on_its_line_is_read_before_the_body_and_a_here_string_has_none(self):
        found = shell_reader.read('cat <<A <<B && git status\na\nA\nb\nB\nls')
        self.assertEqual([(c.words, c.heredocs) for c in found],
                         [(('cat',), ('a\n', 'b\n')), (('git', 'status'), ()), (('ls',), ())])
        (here,) = shell_reader.read('cat <<< "a b" <<<c')
        self.assertEqual((here.words, here.heredocs), (('cat',), ()))

    def test_a_heredoc_that_never_ends_runs_to_the_end(self):
        (command,) = shell_reader.read('cat <<EOF\nbody\nmore')
        self.assertEqual(command.heredocs, ('body\nmore\n',))

    def test_apostrophes_in_a_body_never_reach_the_words(self):
        found = shell_reader.read("git commit -q -F - <<'EOF'\nthe step's and Pi's\nEOF\npython3 -m unittest discover")
        self.assertEqual([c.words for c in found],
                         [('git', 'commit', '-q', '-F', '-'), ('python3', '-m', 'unittest', 'discover')])
        self.assertEqual(found[0].heredocs, ("the step's and Pi's\n",))


class QuoteTest(unittest.TestCase):
    def test_an_unclosed_quote_is_a_character_and_never_merges_lines(self):
        self.assertEqual(words("echo it's fine\ngit status"), [('echo', "it's", 'fine'), ('git', 'status')])
        self.assertEqual(words('echo "a b\ngit status'), [('echo', '"a', 'b'), ('git', 'status')])
        self.assertEqual(words("git commit -m 'x\n\nls"), [('git', 'commit', '-m', "'x"), ('ls',)])
        self.assertEqual(words('echo $(date; ls\nls'), [('echo', '$'), ('date',), ('ls',), ('ls',)])

    def test_unclosed_substitutions_nested_deep_are_still_read_at_once(self):
        started = time.monotonic()
        shell_reader.read('echo ' + '$(' * 40)
        shell_reader.read('echo ' + '"$(' * 40 + "'")
        self.assertLess(time.monotonic() - started, 2)  # each level read twice over would take hours

    def test_no_line_raises(self):
        pieces = ["'", '"', '\\', '$(', '(', ')', '<<', '<<-', '<<<', '>', '&>', '|', '||', '&', ';', '\n', ' ', '#',
                  'EOF', 'git', 'cd', 'x', '$', '2', '-c', 'bash', '{']
        generator = random.Random(1)
        for _ in range(3000):
            shell_reader.read(''.join(generator.choice(pieces) for _ in range(generator.randint(0, 25))))

    def test_a_substitution_is_one_word_with_its_heredoc_and_quotes_kept_and_its_commands_come_first(self):
        message = "$(cat <<'EOF'\nfix(x): it's \"quoted\"\n\nbody ) | ;\nEOF\n)"
        cat, git, ls = shell_reader.read(f'git commit -m "{message}" && ls')
        self.assertEqual((cat.words, cat.heredocs), (('cat',), ('fix(x): it\'s "quoted"\n\nbody ) | ;\n',)))
        self.assertEqual(git.words, ('git', 'commit', '-m', message))
        self.assertEqual(ls.words, ('ls',))
        self.assertEqual(words('echo $(git status | wc) "$(a "b c")" x'),
                         [('git', 'status'), ('wc',), ('a', 'b c'), ('echo', '$(git status | wc)', '$(a "b c")', 'x')])


def folders(line, only='git'):
    """(first word, folder) of each command that is not a cd, or of each named `only`."""
    return [(c.words[0], c.folder) for c in shell_reader.read(line)
            if c.argv[:1] not in (('cd',), ('pushd',)) and only in (None, c.words[0])]


class FolderTest(unittest.TestCase):
    def test_a_cd_moves_the_commands_after_it(self):
        self.assertEqual(folders('cd repo && git commit'), [('git', 'repo')])
        self.assertEqual(folders('cd /abs/web && git status; cd b; git add .'), [('git', '/abs/web'), ('git', '/abs/web/b')])
        self.assertEqual(folders('cd a; cd /b && git x\ngit y'), [('git', '/b'), ('git', '/b')])
        self.assertEqual(folders('pushd sub && git x || git y'), [('git', 'sub'), ('git', 'sub')])
        self.assertEqual(folders('git x'), [('git', '')])

    def test_a_cd_without_a_folder_moves_nothing(self):
        self.assertEqual(folders('cd && git x; cd - && git y; cd -P && git z'), [('git', '')] * 3)

    def test_a_cd_in_a_pipeline_or_the_background_or_a_subshell_stays_there(self):
        self.assertEqual(folders('cd a | git x; ls | cd b && git y; cd c & git z'), [('git', ''), ('git', ''), ('git', '')])
        self.assertEqual(folders('(cd a && git x); git y'), [('git', 'a'), ('git', '')])
        self.assertEqual(folders('cd a && (git x | git y) && git z'), [('git', 'a')] * 3)
        self.assertEqual(folders('cd a | git x | git y'), [('git', ''), ('git', '')])

    def test_a_substitution_and_a_shell_c_run_where_they_are_and_leave_nothing_behind(self):
        self.assertEqual(folders('cd a && echo "$(git x)" $(cd b; git y); git z', only=None),
                         [('git', 'a'), ('git', 'a/b'), ('echo', 'a'), ('git', 'a')])
        self.assertEqual(folders("cd a && bash -c 'cd b && git x'; git y", only=None),
                         [('bash', 'a'), ('git', 'a/b'), ('git', 'a')])

    def test_a_cd_after_a_keyword_or_an_assignment_counts(self):
        self.assertEqual(folders('if true; then cd a; git x; fi', only=None), [('if', ''), ('git', 'a'), ('fi', 'a')])
        self.assertEqual(folders('FOO=1 cd a && git x'), [('git', 'a')])


class ArgvTest(unittest.TestCase):
    def test_argv_is_the_program_and_its_arguments(self):
        for line in ('git commit', 'FOO=1 git commit', 'sudo git commit', 'env A=b git commit',
                     'time nohup git commit', 'if git commit', '! git commit', '/usr/bin/env git commit'):
            (command,) = shell_reader.read(line)
            self.assertEqual(command.argv[-2:], ('git', 'commit'), line)
        (command,) = shell_reader.read('A=1 B=2')
        self.assertEqual(command.argv, ())

    def test_a_shell_given_a_script_has_its_commands_read_too(self):
        found = shell_reader.read('sudo bash -lc "git add . && git commit -m \'a b\'"; sh -x script.sh')
        self.assertEqual([c.words for c in found],
                         [('sudo', 'bash', '-lc', "git add . && git commit -m 'a b'"), ('git', 'add', '.'),
                          ('git', 'commit', '-m', 'a b'), ('sh', '-x', 'script.sh')])


if __name__ == '__main__':
    unittest.main()
