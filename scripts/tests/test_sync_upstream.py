import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from support import ROOT, load

sync = load('upstream/sync-upstream.py')

HEAD = b'> Source: https://x/p\n> Mirror maintained by .github/workflows/sync-cli-docs.yml \xe2\x80\x94 do not edit by hand.\n\n'
LLMS = {'name': 'L', 'description': 'd', 'kind': 'llms', 'index': 'https://x/llms.txt',
        'urls': r'https://x/docs/[A-Za-z0-9._/-]+\.md(\?surface=[a-z]+)?', 'prefix': 'https://x/docs/', 'floor': 2}
GITHUB = {'name': 'G', 'description': 'd', 'kind': 'github', 'owner': 'o', 'repos': {
    'r': {'ref': 'main', 'license': 'MIT', 'paths': [
        {'path': 'guide.html', 'when': 'writing C'},
        {'path': 'docs/*.md', 'when': 'writing docs', 'floor': 2, 'exclude': ['**/CONTRIB.md']}]}},
    'notes': {'Skipped': ['x: why']}}


def failing(*args, **kwargs):
    raise subprocess.CalledProcessError(22, 'curl', stderr=b'HTTP 404')


def quiet(function, *args, **kwargs):
    """(result, stdout, stderr) of a call."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = function(*args, **kwargs)
    return result, out.getvalue(), err.getvalue()


class ConfigTest(unittest.TestCase):
    def check(self, spec):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'c.json'
            path.write_text(json.dumps({'version': 1, 'sources': {'s': spec}}))
            return sync.sources(path)

    def test_real_config_is_valid(self):
        self.assertEqual(list(sync.sources()), ['claude', 'codex', 'pi', 'antigravity', 'google', 'facebook'])

    def test_valid_specs_pass(self):
        self.assertEqual(list(self.check(LLMS)), ['s'])
        self.assertEqual(list(self.check(GITHUB)), ['s'])

    def test_bad_specs_fail(self):
        bad = [dict(LLMS, kind='rss'), dict(LLMS, extra=1), {k: v for k, v in LLMS.items() if k != 'floor'},
               dict(LLMS, floor=0), dict(LLMS, floor=True), dict(LLMS, notes={'T': 'not a list'}),
               dict(GITHUB, repos={}), dict(GITHUB, repos={'r': {'ref': 'main', 'paths': []}}),
               dict(GITHUB, repos={'r': {'ref': 'main', 'license': 'MIT', 'paths': [{'path': 'a/*.md', 'when': 'w'}]}}),
               dict(GITHUB, repos={'r': {'ref': 'main', 'license': 'MIT', 'paths': [{'path': 'a.md'}]}}),
               dict(GITHUB, repos={'r': {'ref': 'main', 'license': 'MIT', 'paths': [{'path': 'a.md', 'when': 'w', 'floor': 1}]}}),
               dict(GITHUB, repos={'r': {'ref': 'main', 'license': 'MIT', 'paths': [{'path': 'a.md', 'when': 'w', 'convert': 'no'}]}})]
        for spec in bad:
            with self.assertRaises(ValueError, msg=spec):
                self.check(spec)

    def test_source_id_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'c.json'
            path.write_text(json.dumps({'version': 1, 'sources': {'Bad Id': LLMS}}))
            with self.assertRaises(ValueError):
                sync.sources(path)


class PathTest(unittest.TestCase):
    def test_glob_regex(self):
        self.assertTrue(sync.glob_regex('go/*.md').match('go/guide.md'))
        self.assertFalse(sync.glob_regex('go/*.md').match('go/sub/x.md'))
        self.assertTrue(sync.glob_regex('review/**/*.md').match('review/index.md'))
        self.assertTrue(sync.glob_regex('review/**/*.md').match('review/reviewer/speed.md'))
        self.assertTrue(sync.glob_regex('**/CONTRIB.md').match('a/b/CONTRIB.md'))
        self.assertFalse(sync.glob_regex('a.md').match('a_md'))

    def test_select(self):
        paths = {'guide.html', 'docs/a.md', 'docs/b.md', 'docs/CONTRIB.md', 'docs/deep/c.md'}
        self.assertEqual(sync.select(paths, {'path': 'guide.html'}), ['guide.html'])
        self.assertEqual(sync.select(paths, {'path': 'missing.md'}), [])
        self.assertEqual(sync.select(paths, GITHUB['repos']['r']['paths'][1]), ['docs/a.md', 'docs/b.md'])

    def test_mirrored_name(self):
        self.assertEqual(sync.mirrored_name('cppguide.html'), 'cppguide.md')
        self.assertEqual(sync.mirrored_name('doc/style.rst'), 'doc/style.md')
        self.assertEqual(sync.mirrored_name('guide.mdx'), 'guide.mdx')
        self.assertEqual(sync.mirrored_name('guide.html', convert=False), 'guide.html')

    def test_when_for(self):
        spec = dict(GITHUB)
        self.assertEqual(sync.when_for(spec, 'r/guide.md'), 'writing C')  # the converted name
        self.assertEqual(sync.when_for(spec, 'r/docs/a.md'), 'writing docs')
        self.assertIsNone(sync.when_for(spec, 'r/docs/CONTRIB.md'))
        self.assertIsNone(sync.when_for(spec, 'other/x.md'))
        self.assertIsNone(sync.when_for(LLMS, 'x.md'))


class PageTest(unittest.TestCase):
    def test_page_matches_the_bash_output(self):
        self.assertEqual(sync.page('https://x/p', b'body\n\n'), HEAD + b'body\n')
        self.assertEqual(sync.page('https://x/p', b'no newline'), HEAD + b'no newline\n')

    def test_page_extra_header_lines(self):
        data = sync.page('https://x/p', b'b', 'MIT', 'html')
        self.assertIn(b'\n> License: MIT\n> Converted from html with pandoc.\n\nb\n', data)

    def test_outline(self):
        text = ('> Source: x\n> Mirror\n\n---\ntitle: front\n---\n# Title #\n\ntext\n```\n# not a heading\n```\n'
                '## Sub ##\nPara\n---\nSetext one\n===\n- item\n---\n~~~\n### nor this\n~~~\n#### Deep <a id="x"></a>\n')
        self.assertEqual(sync.outline(text), [[1, 'Title', 7], [2, 'Sub', 13], [2, 'Para', 14], [1, 'Setext one', 16], [4, 'Deep', 23]])

    def test_title_of(self):
        self.assertEqual(sync.title_of([[2, 'Sub', 3], [1, 'Top', 9]], 'f'), 'Top')
        self.assertEqual(sync.title_of([[2, 'Sub', 3]], 'f'), 'Sub')
        self.assertEqual(sync.title_of([], 'f'), 'f')

    def test_meta_counts_the_written_file(self):
        data = sync.page('https://x/p', b'# T\n\n## S\n')
        entry = sync.meta('a.md', data, when='w')
        self.assertEqual((entry['title'], entry['when'], entry['bytes'], entry['lines']), ('T', 'w', len(data), 6))
        self.assertEqual(entry['headings'], [[1, 'T', 4], [2, 'S', 6]])
        self.assertEqual(sync.meta('pylintrc', b'# comment\n')['headings'], [])

    def test_descriptions(self):
        known = sync.descriptions('# T\n- [Overview](https://x/docs/overview.md): What it is.\n- [Rules](https://x/docs/rules)\n'
                                  '- [Cli](https://x/docs/cli.md?surface=cli): CLI view\n')
        self.assertEqual(known['https://x/docs/overview.md'], ('Overview', 'What it is.'))
        self.assertEqual(sync.described(known, 'https://x/docs/overview'), ('Overview', 'What it is.'))
        self.assertEqual(sync.described(known, 'https://x/docs/rules'), ('Rules', None))
        self.assertEqual(sync.described(known, 'https://x/docs/cli?surface=cli'), ('Cli', 'CLI view'))
        self.assertEqual(sync.described(known, 'https://x/docs/none'), (None, None))


class IndexTest(unittest.TestCase):
    pages = [{'path': 'r/docs/a.md', 'title': 'A', 'description': None, 'when': 'writing docs', 'source': 's', 'license': 'MIT',
              'commit': 'c', 'bytes': 2048, 'lines': 3, 'headings': [[1, 'A', 4]]},
             {'path': 'r/guide.md', 'title': 'G', 'description': 'desc', 'when': 'writing C', 'source': 's', 'license': 'MIT',
              'commit': None, 'bytes': 10, 'lines': 1, 'headings': []}]

    def test_index_json_round_trips_one_page_per_line(self):
        data = {'version': 1, 'source': 's', 'name': 'N', 'description': 'd', 'pages': self.pages, 'notes': {'K': ['v']}}
        text = sync.index_json(data)
        self.assertEqual(json.loads(text), data)
        self.assertEqual(sum(line.startswith(' {"path"') for line in text.splitlines()), 2)

    def test_index_md_github_groups_by_repo_with_when_and_notes(self):
        text = sync.index_md(GITHUB, self.pages)
        self.assertIn('## r (`main`, MIT)', text)
        self.assertIn('| writing docs | [r/docs/a.md](r/docs/a.md) | 2 |', text)
        self.assertIn('| writing C | [r/guide.md](r/guide.md) | 1 |', text)
        self.assertIn('## Skipped\n\n- x: why\n', text)

    def test_index_md_llms_lists_descriptions(self):
        text = sync.index_md(LLMS, self.pages)
        self.assertIn('- [r/docs/a.md](r/docs/a.md)\n- [r/guide.md](r/guide.md): desc\n', text)
        self.assertIn('Pages: 2', text)


class SyncTest(unittest.TestCase):
    def test_sync_llms(self):
        index = ('- [A](https://x/docs/a.md): About a\n- [B](https://x/docs/b.md)\n- [C](https://x/docs/c.md?surface=cli)\n'
                 '- [H](https://x/docs/html.md)\n- [F](https://x/docs/fail.md)\n')
        bodies = {'https://x/llms.txt': index.encode(), 'https://x/docs/a.md': b'# A\n', 'https://x/docs/b.md': b'# B\n',
                  'https://x/docs/c.md?surface=cli': b'# C\n', 'https://x/docs/html.md': b'<!DOCTYPE html>'}
        fake = lambda url, headers=(): bodies[url] if url in bodies else failing()
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(sync, 'fetch', fake):
            pages, misses, ok = sync.sync_llms('s', LLMS, Path(temp), '')
            self.assertEqual([p['path'] for p in pages], ['a.md', 'b.md', 'c.surface-cli.md'])
            self.assertEqual((pages[0]['source'], pages[0]['description']), ('https://x/docs/a', 'About a'))
            self.assertEqual(pages[2]['source'], 'https://x/docs/c?surface=cli')
            self.assertEqual((Path(temp) / 'a.md').read_bytes(), b'> Source: https://x/docs/a\n' + HEAD[len(b'> Source: https://x/p\n'):] + b'# A\n')
            self.assertEqual(len(misses), 2)
            self.assertTrue(ok)
            pages, misses, ok = sync.sync_llms('s', dict(LLMS, floor=4), Path(temp), '')
            self.assertFalse(ok)
            pages, misses, ok = sync.sync_llms('s', dict(LLMS, floor=9), Path(temp), '')
            self.assertEqual((pages, ok), ([], False))
            self.assertIn('lists 5 pages (< 9)', misses[0])

    def test_sync_docs_json(self):
        nav = {'navigation': [{'title': 'Start', 'items': [{'title': 'Overview', 'path': 'index.md'}, {'title': 'Use', 'path': 'usage.md'},
                                                           {'title': 'Ext', 'path': 'https://x/y.md'}, {'title': 'Up', 'path': '../z.md'}]}]}
        spec = {'name': 'P', 'description': 'd', 'kind': 'docs-json', 'index': 'https://x/docs.json', 'raw': 'https://raw/x', 'pages': 'https://gh/x', 'floor': 2}
        bodies = {'https://x/docs.json': json.dumps(nav).encode(), 'https://raw/x/index.md': b'intro\n', 'https://raw/x/usage.md': b'# Usage\n'}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(sync, 'fetch', lambda url, headers=(): bodies[url]):
            pages, misses, ok = sync.sync_docs_json('p', spec, Path(temp), '')
            self.assertEqual([(p['path'], p['title'], p['source']) for p in pages],
                             [('index.md', 'Overview', 'https://gh/x/index.md'), ('usage.md', 'Usage', 'https://gh/x/usage.md')])
            self.assertEqual((misses, ok), ([], True))

    def github_run(self, tree, bodies, spec=GITHUB, pandoc=lambda body, reader: b'# Converted\n\n' + body):
        fake_fetch = lambda url, headers=(): bodies[url] if url in bodies else failing()
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(sync, 'api', lambda path, auth: tree), \
                mock.patch.object(sync, 'fetch', fake_fetch), mock.patch.object(sync, 'pandoc', pandoc), \
                mock.patch.object(sync, 'last_commit', lambda *a: 'abc123'):
            (pages, misses, ok), _, err = quiet(sync.sync_github, 'g', spec, Path(temp), '')
            files = {p.relative_to(temp).as_posix(): p.read_bytes() for p in Path(temp).rglob('*') if p.is_file()}
        return pages, misses, ok, files, err

    def test_sync_github_converts_labels_and_pins(self):
        tree = {'tree': [{'path': p, 'type': 'blob'} for p in ('guide.html', 'docs/a.md', 'docs/b.md', 'docs/CONTRIB.md')] + [{'path': 'docs', 'type': 'tree'}]}
        raw = 'https://raw.githubusercontent.com/o/r/main/'
        bodies = {raw + 'guide.html': b'<h1>Guide</h1>', raw + 'docs/a.md': b'# A\n', raw + 'docs/b.md': b'# B\n'}
        pages, misses, ok, files, err = self.github_run(tree, bodies)
        self.assertEqual((misses, ok), ([], True))
        self.assertEqual(sorted(files), ['r/docs/a.md', 'r/docs/b.md', 'r/guide.md'])
        self.assertTrue(files['r/guide.md'].startswith(b'> Source: https://github.com/o/r/blob/main/guide.html\n'))
        self.assertIn(b'> License: MIT\n> Converted from html with pandoc.\n\n# Converted\n', files['r/guide.md'])
        self.assertNotIn(b'Converted', files['r/docs/a.md'])
        by_path = {p['path']: p for p in pages}
        self.assertEqual((by_path['r/guide.md']['when'], by_path['r/guide.md']['commit'], by_path['r/docs/a.md']['when']), ('writing C', 'abc123', 'writing docs'))

    def test_sync_github_misses_fail_the_source(self):
        raw = 'https://raw.githubusercontent.com/o/r/main/'
        tree = {'tree': [{'path': p, 'type': 'blob'} for p in ('guide.html', 'docs/a.md')], 'truncated': True}
        pages, misses, ok, files, err = self.github_run(tree, {raw + 'guide.html': b'<p>x</p>', raw + 'docs/a.md': b'a'})
        self.assertFalse(ok)
        self.assertEqual(misses, ['r/docs/*.md: 1 of 2 files in the tree'])
        self.assertIn('truncated', err)
        tree = {'tree': [{'path': 'docs/a.md', 'type': 'blob'}, {'path': 'docs/b.md', 'type': 'blob'}]}
        pages, misses, ok, files, err = self.github_run(tree, {raw + 'docs/a.md': b'a', raw + 'docs/b.md': b'b'})
        self.assertEqual(misses, ['r/guide.html: 0 of 1 files in the tree'])
        tree = {'tree': [{'path': p, 'type': 'blob'} for p in ('guide.html', 'docs/a.md', 'docs/b.md')]}
        pages, misses, ok, files, err = self.github_run(tree, {raw + 'guide.html': b'x', raw + 'docs/a.md': b'a'})
        self.assertEqual(misses, ['r/docs/b.md: fetch failed (HTTP 404)'])

        def no_pandoc(body, reader):
            raise FileNotFoundError('pandoc')
        pages, misses, ok, files, err = self.github_run(tree, {raw + 'guide.html': b'x', raw + 'docs/a.md': b'a', raw + 'docs/b.md': b'b'}, pandoc=no_pandoc)
        self.assertEqual(len(misses), 1)
        self.assertIn('pandoc is not installed', misses[0])


class FinishTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mirror = Path(self.temp.name)
        (self.mirror / 's').mkdir()
        (self.mirror / 's/old.md').write_bytes(sync.page('https://x/old', b'# Old\n'))
        self.stage = self.mirror / 's.tmp'
        self.stage.mkdir()
        self.data = sync.page('https://x/docs/new', b'# New\n')
        (self.stage / 'new.md').write_bytes(self.data)
        self.pages = [sync.meta('new.md', self.data, source='https://x/docs/new')]

    def tearDown(self):
        self.temp.cleanup()

    def test_failure_keeps_the_previous_copy(self):
        done, out, err = quiet(sync.finish, self.mirror, 's', LLMS, self.stage, self.pages, ['index too small'], False)
        self.assertFalse(done)
        self.assertTrue((self.mirror / 's/old.md').is_file())
        self.assertIn('WARN: index too small', err)
        self.assertIn('keeping the previous', err)

    def test_success_swaps_and_indexes(self):
        done, out, err = quiet(sync.finish, self.mirror, 's', LLMS, self.stage, self.pages, [], True)
        self.assertTrue(done)
        self.assertFalse((self.mirror / 's/old.md').exists())
        self.assertFalse(self.stage.exists())
        index = json.loads((self.mirror / 's/MIRROR-INDEX.json').read_text())
        self.assertEqual([p['path'] for p in index['pages']], ['new.md'])
        self.assertIn('- [new.md](new.md)', (self.mirror / 's/MIRROR-INDEX.md').read_text())

    def test_case_clash_warns(self):
        pages = self.pages + [dict(self.pages[0], path='NEW.md')]
        done, out, err = quiet(sync.finish, self.mirror, 's', LLMS, self.stage, pages, [], True)
        self.assertIn('differ only in case', err)

    def test_reindex_keeps_commits_and_reads_headers(self):
        quiet(sync.finish, self.mirror, 's', LLMS, self.stage, self.pages, [], True)
        index = json.loads((self.mirror / 's/MIRROR-INDEX.json').read_text())
        index['pages'][0]['commit'] = 'kept'
        (self.mirror / 's/MIRROR-INDEX.json').write_text(json.dumps(index))
        known = b'- [New page](https://x/docs/new.md): Fresh description\n'
        with mock.patch.object(sync, 'fetch', lambda url, headers=(): known):
            done, out, err = quiet(sync.reindex, self.mirror, 's', LLMS)
        self.assertTrue(done)
        page = json.loads((self.mirror / 's/MIRROR-INDEX.json').read_text())['pages'][0]
        self.assertEqual((page['commit'], page['description'], page['source'], page['title']), ('kept', 'Fresh description', 'https://x/docs/new', 'New'))
        with mock.patch.object(sync, 'fetch', failing):
            done, out, err = quiet(sync.reindex, self.mirror, 's', LLMS)
        self.assertTrue(done)
        self.assertIn('descriptions come from the previous index', err)
        self.assertEqual(json.loads((self.mirror / 's/MIRROR-INDEX.json').read_text())['pages'][0]['description'], 'Fresh description')

    def test_reindex_labels_github_pages_from_config(self):
        (self.mirror / 'g/r/docs').mkdir(parents=True)
        (self.mirror / 'g/r/guide.md').write_bytes(sync.page('https://github.com/o/r/blob/main/guide.html', b'# G\n', 'MIT', 'html'))
        (self.mirror / 'g/r/docs/a.md').write_bytes(sync.page('https://github.com/o/r/blob/main/docs/a.md', b'# A\n', 'MIT'))
        done, out, err = quiet(sync.reindex, self.mirror, 'g', GITHUB)
        pages = {p['path']: p for p in json.loads((self.mirror / 'g/MIRROR-INDEX.json').read_text())['pages']}
        self.assertEqual((pages['r/guide.md']['when'], pages['r/guide.md']['license'], pages['r/docs/a.md']['when']), ('writing C', 'MIT', 'writing docs'))
        self.assertIn('| writing C | [r/guide.md](r/guide.md) |', (self.mirror / 'g/MIRROR-INDEX.md').read_text())

    def test_catalog_lists_sources_in_config_order(self):
        quiet(sync.finish, self.mirror, 's', LLMS, self.stage, self.pages, [], True)
        (self.mirror / 'extra').mkdir()
        (self.mirror / 'extra/MIRROR-INDEX.json').write_text(json.dumps({'pages': [], 'description': 'leftover'}))
        sync.write_catalog(self.mirror, {'zz': LLMS, 's': LLMS})
        text = (self.mirror / 'INDEX.md').read_text()
        self.assertIn('| [s](s/MIRROR-INDEX.md) | llms | 1 | d |', text)
        self.assertIn('| [extra](extra/MIRROR-INDEX.md) | ? | 0 | leftover |', text)
        self.assertLess(text.index('[s]'), text.index('[extra]'))


class MainTest(unittest.TestCase):
    def test_unknown_source(self):
        with tempfile.TemporaryDirectory() as temp:
            status, out, err = quiet(sync.main, ['nope', '--mirror', temp])
        self.assertEqual(status, 1)
        self.assertIn('Unknown source: nope', err)

    def test_failed_source_keeps_previous_and_cleans_stage(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(sync, 'fetch', failing), mock.patch.object(sync, 'token', lambda: ''):
            mirror = Path(temp)
            (mirror / 'pi').mkdir()
            (mirror / 'pi/old.md').write_bytes(sync.page('https://x/old', b'old'))
            status, out, err = quiet(sync.main, ['pi', '--mirror', temp])
            self.assertEqual(status, 1)
            self.assertTrue((mirror / 'pi/old.md').is_file())
            self.assertFalse((mirror / 'pi.tmp').exists())
            self.assertIn('keeping the previous', err)

    def test_index_only_without_pages_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            status, out, err = quiet(sync.main, ['google', '--index-only', '--mirror', temp])
        self.assertEqual(status, 1)
        self.assertIn('nothing to index', err)


if __name__ == '__main__':
    unittest.main()
