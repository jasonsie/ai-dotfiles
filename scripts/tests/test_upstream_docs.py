import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'skills/upstream-docs/query.py'
spec = importlib.util.spec_from_file_location('upstream_query', SCRIPT)
assert spec and spec.loader, SCRIPT
query = importlib.util.module_from_spec(spec)
spec.loader.exec_module(query)

STYLE = '''\
> Source: https://example.com/alpha/style.md
> License: CC-BY-3.0

# Alpha Style Guide
Intro.
## 1 Naming
Use short names.
### 1.1 Variables
Variables are lower_case.
```sh
# not a heading
echo hi
```
## 2 Formatting
Line length is 80.
'''
PYLINTRC = '> Source: https://example.com/alpha/pylintrc\n> License: Apache-2.0\n\n[MESSAGES CONTROL]\ndisable=C0114\n'
REVIEW = '''\
> Source: https://example.com/beta/review.md
> License: MIT

# Beta Review Guide
## Naming things
Pick clear names.
## Naming review comments
Be kind.
## Scope
Keep it small.
### Scope creep
Split big changes.
'''
FAQ = '\n'.join(['> Source: https://example.com/beta/faq.md', '> License: MIT', '', '# Beta FAQ', '## Examples',
                 'answer 1 ' + 'x' * 200, *[f'answer {n}' for n in range(2, 36)], '## Examples', 'more']) + '\n'
# bytes only feeds the size shown, so some pages set it to hit the rounding cases
ALPHA = {
    'guide/style.md': ({'title': 'Alpha Style Guide', 'when': 'writing alpha code', 'bytes': 2560,
                        'description': 'Rules for names and layout.',
                        'headings': [[1, 'Alpha Style Guide', 4], [2, '1 Naming', 6], [3, '1.1 Variables', 8],
                                     [2, '2 Formatting', 14]]}, STYLE),
    'tools/pylintrc': ({'title': 'Alpha pylintrc', 'when': None, 'description': 'Shared lint notes.'}, PYLINTRC),
}
BETA = {
    'docs/review.md': ({'title': 'Beta Review Guide', 'when': 'naming a function', 'bytes': 1600,
                        'description': 'Review notes.',
                        'headings': [[1, 'Beta Review Guide', 4], [2, 'Naming things', 5],
                                     [2, 'Naming review comments', 7], [2, 'Scope', 9], [3, 'Scope creep', 11]]}, REVIEW),
    'docs/faq.md': ({'title': 'Beta FAQ', 'description': 'Short notes.', 'bytes': 4096,
                     'headings': [[1, 'Beta FAQ', 4], [2, 'Examples', 5], [2, 'Examples', 41]]}, FAQ),
}


def add_source(mirror, source, pages, **meta):
    """Write {path: (index fields, text)} under mirror/source, with a MIRROR-INDEX.json for it."""
    (mirror / source).mkdir(parents=True, exist_ok=True)
    entries = []
    for path, (fields, text) in pages.items():
        (mirror / source / path).parent.mkdir(parents=True, exist_ok=True)
        (mirror / source / path).write_text(text)
        entries.append({'path': path, 'bytes': 100, 'lines': text.count('\n'), **fields})
    index = {'version': 1, 'source': source, 'name': f'{source.title()} docs',
             'description': f'Fixture source {source}.', 'pages': entries, **meta}
    (mirror / source / 'MIRROR-INDEX.json').write_text(json.dumps(index))


class UpstreamDocsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mirror = Path(tmp.name)
        add_source(self.mirror, 'alpha', ALPHA)
        add_source(self.mirror, 'beta', BETA)

    def run_query(self, *args, mirror=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = query.main(['--mirror', str(mirror or self.mirror), *args])
        return code, out.getvalue(), err.getvalue()

    def ok(self, *args):
        code, out, err = self.run_query(*args)
        self.assertEqual((code, err), (0, ''))
        return out

    def test_fixture_headings_sit_on_the_lines_the_index_names(self):
        for source in ('alpha', 'beta'):
            for page in json.loads((self.mirror / source / 'MIRROR-INDEX.json').read_text())['pages']:
                lines = (self.mirror / source / page['path']).read_text().splitlines()
                self.assertEqual(len(lines), page['lines'])
                for level, text, number in page.get('headings', []):
                    self.assertEqual(lines[number - 1], '#' * level + ' ' + text)

    def test_default_mirror_is_this_repos_docs_upstream(self):
        self.assertEqual(query.MIRROR, ROOT / 'docs/upstream')

    def test_list(self):
        self.assertEqual(self.ok('list'), 'alpha  2 pages  Alpha docs: Fixture source alpha.\n'
                                          'beta  2 pages  Beta docs: Fixture source beta.\n')
        add_source(self.mirror, 'gamma', {}, description=None)
        self.assertTrue(self.ok('list').endswith('gamma  0 pages  Gamma docs\n'))

    def test_find_ranks_a_when_match_above_a_heading_only_match(self):
        hits = ('beta/docs/review.md — Beta Review Guide [naming a function] (2 KB)\n'
                '  L5  ## Naming things\n  L7  ## Naming review comments\n')
        style = 'alpha/guide/style.md — Alpha Style Guide [writing alpha code] (3 KB)\n  L6  ## 1 Naming\n'
        self.assertEqual(self.ok('find', 'naming'), hits + style)
        self.assertEqual(self.ok('find', 'NAMING', '--limit', '1'), hits)
        self.assertEqual(self.ok('find', 'naming', '--source', 'alpha'), style)
        both = self.ok('find', 'naming', 'alpha').splitlines()
        self.assertEqual([line.split(' — ')[0] for line in both if line[0] != ' '],
                         ['alpha/guide/style.md', 'beta/docs/review.md', 'alpha/tools/pylintrc'])

    def test_find_ties_put_outlined_pages_first_then_by_reference_and_sizes_round_up_to_one_kb(self):
        self.assertEqual(self.ok('find', 'notes'), 'beta/docs/faq.md — Beta FAQ (4 KB)\n'
                                                  'beta/docs/review.md — Beta Review Guide [naming a function] (2 KB)\n'
                                                  'alpha/tools/pylintrc — Alpha pylintrc (1 KB)\n')

    def test_find_counts_at_most_three_headings_per_term(self):
        steps = [[2, f'Step {n}', n + 3] for n in range(1, 6)]
        add_source(self.mirror, 'gamma', {'many.md': ({'title': 'Many', 'headings': steps}, ''),
                                          'title.md': ({'title': 'Step guide'}, '')})
        self.assertEqual(self.ok('find', 'step', '--source', 'gamma'),
                         'gamma/title.md — Step guide (1 KB)\ngamma/many.md — Many (1 KB)\n'
                         '  L4  ## Step 1\n  L5  ## Step 2\n  L6  ## Step 3\n')

    def test_find_without_a_match_or_with_an_unknown_source(self):
        self.assertEqual(self.ok('find', 'zzz'), 'no match\n')
        code, out, err = self.run_query('find', 'x', '--source', 'gamma')
        self.assertEqual((code, out, err), (1, '', 'unknown source: gamma (known: alpha, beta)\n'))

    def test_find_reads_no_page_file_without_grep(self):
        (self.mirror / 'alpha/guide/style.md').unlink()
        self.assertIn('alpha/guide/style.md', self.ok('find', 'naming'))

    def test_find_grep_lists_lines_that_hold_every_term_after_the_index_hits(self):
        self.assertEqual(self.ok('find', 'line', '80', '--grep'), 'grep:\nalpha/guide/style.md:L15: Line length is 80.\n')
        out = self.ok('find', 'naming', '--grep', '--limit', '1')
        self.assertEqual(out.split('grep:\n')[1].splitlines(), ['alpha/guide/style.md:L6: ## 1 Naming',
                         'beta/docs/review.md:L5: ## Naming things', 'beta/docs/review.md:L7: ## Naming review comments'])
        self.assertEqual(self.ok('find', 'length', '--grep', '--source', 'beta'), 'no match\n')
        self.assertEqual(self.ok('find', 'example.com', '--grep'), 'no match\n')

    def test_find_grep_stops_at_30_lines_and_cuts_lines_to_120_characters(self):
        rows = self.ok('find', 'answer', '--grep').splitlines()[1:]
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0], 'beta/docs/faq.md:L6: answer 1 ' + 'x' * (120 - len('answer 1 ')))
        self.assertEqual(rows[-1], 'beta/docs/faq.md:L35: answer 30')

    def test_outline_hides_levels_below_the_depth(self):
        self.assertEqual(self.ok('outline', 'alpha/guide/style.md'),
                         'alpha/guide/style.md — Alpha Style Guide (15 lines, 4 headings)\n'
                         'L4  # Alpha Style Guide  (12 lines)\nL6  ## 1 Naming  (8 lines)\nL14  ## 2 Formatting  (2 lines)\n')
        deeper = self.ok('outline', 'alpha/guide/style.md', '--depth', '3')
        self.assertIn('L6  ## 1 Naming  (8 lines)\nL8  ### 1.1 Variables  (6 lines)\n', deeper)
        self.assertNotIn('not a heading', deeper)

    def test_outline_of_a_page_without_headings(self):
        self.assertEqual(self.ok('outline', 'alpha/tools/pylintrc'),
                         'alpha/tools/pylintrc — Alpha pylintrc (5 lines, 0 headings)\nno headings (not Markdown?)\n')

    def test_outline_sizes_equal_the_lines_show_prints_for_the_heading(self):
        for ref in ('alpha/guide/style.md', 'beta/docs/review.md'):
            for text, size in re.findall(r'^L\d+  #+ (.*)  \((\d+) lines\)$', self.ok('outline', ref, '--depth', '6'), re.M):
                self.assertEqual(len(self.ok('show', ref, '--heading', text).splitlines()) - 1, int(size), (ref, text))

    def test_show_heading_stops_at_the_next_heading_of_its_level(self):
        self.assertEqual(self.ok('show', 'beta/docs/review.md', '--heading', 'Naming things'),
                         '# beta/docs/review.md L5-L6 of 12\n## Naming things\nPick clear names.\n')

    def test_show_heading_keeps_deeper_sections_and_fenced_comments(self):
        out = self.ok('show', 'alpha/guide/style.md', '--heading', '1 Naming').splitlines()
        self.assertEqual(out[0], '# alpha/guide/style.md L6-L13 of 15')
        self.assertEqual(out[1:], STYLE.splitlines()[5:13])
        self.assertIn('# not a heading', out)

    def test_show_heading_matches_exact_then_prefix_then_substring_ignoring_case(self):
        for text, rows in (('scope', 'L9-L12'), ('Naming R', 'L7-L8'), ('COMMENTS', 'L7-L8')):
            first = self.ok('show', 'beta/docs/review.md', '--heading', text).splitlines()[0]
            self.assertEqual(first, f'# beta/docs/review.md {rows} of 12')

    def test_show_heading_that_is_ambiguous_or_missing(self):
        candidates = 'ambiguous heading; candidates:\n'
        self.assertEqual(self.run_query('show', 'beta/docs/review.md', '--heading', 'naming'),
                         (2, candidates + '  L5  ## Naming things\n  L7  ## Naming review comments\n', ''))
        self.assertEqual(self.run_query('show', 'beta/docs/faq.md', '--heading', 'examples'),
                         (2, candidates + '  L5  ## Examples\n  L41  ## Examples\n', ''))
        self.assertEqual(self.run_query('show', 'beta/docs/review.md', '--heading', 'zzz'),
                         (1, 'no heading matches "zzz"\n', ''))

    def test_show_lines_and_the_whole_page(self):
        self.assertEqual(self.ok('show', 'alpha/guide/style.md', '--lines', '10-12'),
                         '# alpha/guide/style.md L10-L12 of 15\n```sh\n# not a heading\necho hi\n')
        self.assertEqual(self.ok('show', 'alpha/guide/style.md', '--lines', '14-99'),
                         '# alpha/guide/style.md L14-L15 of 15\n## 2 Formatting\nLine length is 80.\n')
        self.assertEqual(self.ok('show', 'alpha/tools/pylintrc'), '# alpha/tools/pylintrc L1-L5 of 5\n' + PYLINTRC)
        code, out, err = self.run_query('show', 'alpha/guide/style.md', '--lines', '16-20')
        self.assertEqual((code, out, err), (1, '', 'alpha/guide/style.md has 15 lines, not 16-20\n'))

    def test_show_truncates_with_a_hint_to_continue(self):
        out = self.ok('show', 'beta/docs/faq.md', '--max-lines', '5').splitlines()
        self.assertEqual((out[0], len(out), out[-1]), ('# beta/docs/faq.md L1-L42 of 42', 7, '… 37 more lines; use --lines 6-42'))
        out = self.ok('show', 'alpha/guide/style.md', '--heading', '1 Naming', '--max-lines', '3').splitlines()
        self.assertEqual((out[0], out[-1]), ('# alpha/guide/style.md L6-L13 of 15', '… 5 more lines; use --lines 9-13'))
        self.assertNotIn('more lines', self.ok('show', 'beta/docs/faq.md'))

    def test_unknown_page_is_an_error(self):
        for command in ('outline', 'show'):
            for ref in ('alpha/nope.md', 'gamma/x.md', 'alpha'):
                self.assertEqual(self.run_query(command, ref), (1, '', f'unknown page: {ref}\n'))

    def test_missing_indexes_are_an_error(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(self.run_query('list', mirror=empty), (1, '', f'no MIRROR-INDEX.json under {empty}\n'))

    def test_bad_arguments_are_usage_errors(self):
        style = 'alpha/guide/style.md'
        for args in (('show', style, '--lines', '5'), ('show', style, '--lines', '9-3'),
                     ('show', style, '--heading', 'x', '--lines', '1-2'), ('find',), ()):
            with self.assertRaises(SystemExit) as caught:
                self.run_query(*args)
            self.assertEqual(caught.exception.code, 2, args)

    def test_runs_as_a_script(self):
        done = subprocess.run(['python3', str(SCRIPT), '--mirror', str(self.mirror), 'list'], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout.startswith('alpha  2 pages')), (0, True))
        helped = subprocess.run(['python3', str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual((helped.returncode, 'usage:' in helped.stdout), (0, True))


class RankTest(unittest.TestCase):
    def test_ties_prefer_pages_with_an_outline(self):
        guide = (12, 'g/zz.md', {'headings': [[1, 'T', 4]]})
        config = (12, 'g/aa.vim', {'headings': []})
        better = (13, 'g/zz.vim', {'headings': []})
        self.assertEqual(sorted([config, guide, better], key=query.rank_key), [better, guide, config])


if __name__ == '__main__':
    unittest.main()
