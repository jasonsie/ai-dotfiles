import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'skills/collect-docs/survey.py'
spec = importlib.util.spec_from_file_location('survey', SCRIPT)
assert spec and spec.loader
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)

FIELDS = 'name,description,repositoryTopics,isArchived,isFork,pushedAt,licenseInfo,defaultBranchRef'
HEADER = ['| Repo | Branch | Archived | Fork | License | Pushed | File | KB |', '|---|---|---|---|---|---|---|---|']
SERVER_ROW = '| o/server | main |  |  | Apache-2.0 | 2026-09-01 | docs/Coding-Guide.MD | 1.0 |'


def entry(name, description=None, topics=None, archived=False, fork=False, license_info=None, branch='main'):
    """A `gh repo list` entry; real listings have null topics, licenseInfo (no spdxId) and default branch."""
    return {'name': name, 'description': description, 'repositoryTopics': topics, 'isArchived': archived,
            'isFork': fork, 'pushedAt': '2026-09-01T10:20:30Z', 'licenseInfo': license_info,
            'defaultBranchRef': {'name': branch} if branch else None}


def blob(path, size):
    return {'path': path, 'type': 'blob', 'size': size}


def tree(repo, branch, entries, truncated=False):
    return ('api', f'repos/{repo}/git/trees/{branch}?recursive=1'), {'truncated': truncated, 'tree': entries}


def candidate(repo, path, **changes):
    return {'repo': repo, 'branch': 'main', 'archived': False, 'fork': False, 'license': 'MIT',
            'pushed': '2026-09-01', 'path': path, 'kb': 1.5, **changes}


INVENTORY = [
    entry('style-guides', 'House style', [{'name': 'docs'}], license_info={'key': 'mit', 'name': 'MIT License'}),
    entry('tools', None, [{'name': 'conventions'}], archived=True, fork=True, branch='master'),
    entry('server', 'A web server', license_info={'key': 'apache-2.0', 'spdxId': 'Apache-2.0'}),
]
SOLO = {'default_branch': 'trunk', 'archived': False, 'fork': True, 'pushed_at': '2026-08-15T08:00:00Z',
        'license': None, 'description': None, 'topics': []}
RESPONSES = dict([
    tree('o/style-guides', 'main', [
        {'path': 'docs', 'type': 'tree'}, blob('docs/style-guide.md', 2048), blob('CONTRIBUTING.md', 512),
        blob('docs/style-diagram.png', 9000), blob('src/main.py', 10), blob('review/index.md', 2048)]),
    tree('o/tools', 'master', [blob('doc/developers/style.rst', 3000), blob('README.rst', 9)], truncated=True),
    tree('o/server', 'main', [blob('docs/Coding-Guide.MD', 1024), blob('server.go', 5)]),
    tree('o/solo', 'trunk', [blob('CLAUDE.md', 1024), blob('review/index.md', 2048), blob('logo.png', 7)]),
    (('api', 'repos/o/solo'), SOLO),
])


def fake_gh(*args):
    if args[:3] == ('repo', 'list', 'o'):
        assert args[3] == '--limit' and args[5:] == ('--json', FIELDS), args
        return INVENTORY
    if args in RESPONSES:
        return RESPONSES[args]
    raise AssertionError(args)


def run(*argv, gh=fake_gh):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(survey, 'gh', side_effect=gh) as api:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = survey.main(list(argv))
    calls = [call.args for call in api.call_args_list]
    return SimpleNamespace(code=code, out=out.getvalue(), err=err.getvalue(), calls=calls)


class SurveyTest(unittest.TestCase):
    def test_repo_row_normalizes_entries_and_their_nulls(self):
        self.assertEqual(survey.repo_row(INVENTORY[0]), {
            'name': 'style-guides', 'description': 'House style', 'topics': ['docs'], 'archived': False,
            'fork': False, 'pushed': '2026-09-01', 'license': 'mit', 'branch': 'main'})
        self.assertEqual(survey.repo_row(INVENTORY[2])['license'], 'Apache-2.0')
        empty = dict(entry('e'), pushedAt=None, defaultBranchRef=None)
        self.assertEqual(survey.repo_row(empty), {'name': 'e', 'description': '', 'topics': [], 'archived': False,
                                                  'fork': False, 'pushed': '', 'license': 'none', 'branch': ''})

    def test_single_repo_row_is_named_owner_repo(self):
        data = {**SOLO, 'license': {'spdx_id': 'MIT'}, 'description': 'd', 'topics': ['x']}
        self.assertEqual(survey.single_repo_row('o', 'solo', data), {
            'name': 'o/solo', 'description': 'd', 'topics': ['x'], 'archived': False, 'fork': True,
            'pushed': '2026-08-15', 'license': 'MIT', 'branch': 'trunk'})
        self.assertEqual(survey.single_repo_row('o', 'solo', SOLO)['license'], 'none')

    def test_matches_name_topic_or_description_ignoring_case(self):
        row = {'name': 'server', 'description': '', 'topics': []}
        for field, value in (('name', 'Eng-Practices'), ('topics', ['Conventions']),
                             ('description', 'Technical writing')):
            self.assertTrue(survey.matches({**row, field: value}, survey.REPO_PATTERN), field)
        self.assertFalse(survey.matches(row, survey.REPO_PATTERN))

    def test_candidate_files_filter_by_pattern_extension_and_type(self):
        entries = [blob('docs/style-guide.md', 1), {'path': 'docs/style.md', 'type': 'tree'}, blob('docs/style.png', 1),
                   blob('STYLE.MD', 1), blob('README.md', 1), {'path': 'vendor/coding.md', 'type': 'commit'}]
        kept = survey.candidate_files(entries, survey.FILE_PATTERN)
        self.assertEqual([e['path'] for e in kept], ['docs/style-guide.md', 'STYLE.MD'])
        self.assertEqual([e['path'] for e in survey.candidate_files(entries, 'readme')], ['README.md'])

    def test_table_has_a_header_and_rows_sorted_by_repo_then_path(self):
        rows = [candidate('o/b', 'a.md'), candidate('o/a', 'b.md'), candidate('o/a', 'a.md', archived=True, fork=True)]
        self.assertEqual(survey.table(rows).splitlines(), HEADER + [
            '| o/a | main | yes | yes | MIT | 2026-09-01 | a.md | 1.5 |',
            '| o/a | main |  |  | MIT | 2026-09-01 | b.md | 1.5 |',
            '| o/b | main |  |  | MIT | 2026-09-01 | a.md | 1.5 |'])

    def test_org_survey_prints_a_table_and_summarizes_on_stderr(self):
        r = run('o')
        self.assertEqual(r.code, 0)
        self.assertEqual(r.out.splitlines(), HEADER + [
            '| o/style-guides | main |  |  | mit | 2026-09-01 | CONTRIBUTING.md | 0.5 |',
            '| o/style-guides | main |  |  | mit | 2026-09-01 | docs/style-guide.md | 2.0 |',
            '| o/tools | master | yes | yes | none | 2026-09-01 | doc/developers/style.rst | 2.9 |'])
        self.assertIn('warning: o/tools tree truncated; scan it with code search\n', r.err)
        self.assertEqual(r.err.splitlines()[-1], '2 repos scanned, 3 candidate files')
        self.assertNotIn(('api', 'repos/o/server/git/trees/main?recursive=1'), r.calls)

    def test_all_scans_the_repos_the_pattern_drops(self):
        r = run('o', '--all')
        self.assertIn(SERVER_ROW, r.out)
        self.assertEqual(r.err.splitlines()[-1], '3 repos scanned, 4 candidate files')

    def test_pattern_files_and_limit_options(self):
        r = run('o', '--pattern', '^server$', '--files', 'coding', '--limit', '5')
        self.assertEqual(r.calls[0][:5], ('repo', 'list', 'o', '--limit', '5'))
        self.assertEqual(r.out.splitlines(), HEADER + [SERVER_ROW])
        self.assertEqual(r.err, '1 repos scanned, 1 candidate files\n')
        capped = run('o', '--limit', '3')
        self.assertIn('warning: o listing hit --limit 3; raise it to see more repos\n', capped.err)

    def test_owner_repo_skips_the_listing_and_lists_every_document_file(self):
        r = run('o/solo')
        self.assertEqual(r.code, 0)
        self.assertEqual(r.out.splitlines(),
                         HEADER + ['| o/solo | trunk |  | yes | none | 2026-08-15 | CLAUDE.md | 1.0 |',
                                   '| o/solo | trunk |  | yes | none | 2026-08-15 | review/index.md | 2.0 |'])
        self.assertEqual(r.calls, [('api', 'repos/o/solo'), ('api', 'repos/o/solo/git/trees/trunk?recursive=1')])
        self.assertEqual(run('o/solo', '--files', 'claude').out.splitlines()[-1],
                         '| o/solo | trunk |  | yes | none | 2026-08-15 | CLAUDE.md | 1.0 |')
        self.assertNotIn('review/index.md', run('o').out)
        self.assertEqual(run('o/', '--all').out, run('o', '--all').out)

    def test_json_prints_the_candidate_rows(self):
        r = run('o', '--json')
        rows = json.loads(r.out)
        self.assertEqual([row['path'] for row in rows],
                         ['CONTRIBUTING.md', 'docs/style-guide.md', 'doc/developers/style.rst'])
        self.assertEqual(rows[2], candidate('o/tools', 'doc/developers/style.rst', branch='master', archived=True,
                                            fork=True, license='none', kb=2.9))
        self.assertEqual(r.err.splitlines()[-1], '2 repos scanned, 3 candidate files')

    def test_a_failed_tree_call_is_a_warning_not_an_error(self):
        def tools_tree_fails(*args):
            if args[-1].startswith('repos/o/tools/git/trees/'):
                raise subprocess.CalledProcessError(1, ['gh', *args], stderr='gh: Git Repository is empty.\n')
            return fake_gh(*args)
        r = run('o', gh=tools_tree_fails)
        self.assertEqual(r.code, 0)
        self.assertIn('warning: o/tools: gh: Git Repository is empty.; skipped\n', r.err)
        self.assertEqual(r.err.splitlines()[-1], '1 repos scanned, 2 candidate files')

    def test_a_repo_without_a_default_branch_is_skipped(self):
        empty = dict(INVENTORY[0], defaultBranchRef=None)
        r = run('o', gh=lambda *args: [empty] if args[0] == 'repo' else fake_gh(*args))
        self.assertEqual(r.code, 0)
        self.assertEqual(r.err, 'warning: o/style-guides has no default branch; skipped\n'
                                '0 repos scanned, 0 candidate files\n')

    def test_no_candidates_is_success_with_an_empty_table(self):
        r = run('o', '--files', 'zzz')
        self.assertEqual((r.code, r.out.splitlines()), (0, HEADER))
        self.assertEqual(r.err.splitlines()[-1], '2 repos scanned, 0 candidate files')

    def test_gh_failures_print_survey_message_and_return_1(self):
        missing = FileNotFoundError(2, 'No such file or directory', 'gh')
        failed = subprocess.CalledProcessError(1, ['gh'], stderr='gh: Could not resolve to an Organization\n')
        for failure, message in ((missing, "survey: [Errno 2] No such file or directory: 'gh'\n"),
                                 (failed, 'survey: gh: Could not resolve to an Organization\n')):
            r = run('nope', gh=failure)
            self.assertEqual((r.code, r.out, r.err), (1, '', message))


if __name__ == '__main__':
    unittest.main()
