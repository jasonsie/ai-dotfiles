import io
import json
import math
import os
from contextlib import redirect_stdout
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from support import CLIS, load, registry, where
import installer

skills = load('install/skills.py')
ROOTS = sorted({where(cli, 'skills') for cli in CLIS})

MAX_SKILL_BYTES = 20_000
COLLISION_THRESHOLD = 0.75
DISALLOWED_SKILL_FILES = ('test-*.md', 'CREATION-LOG.md')
STOPWORDS = frozenset({
    'a', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'before', 'by', 'for',
    'from', 'in', 'into', 'is', 'it', 'its', 'my', 'need', 'needs', 'of', 'on',
    'or', 'our', 'so', 'that', 'the', 'them', 'this', 'to', 'use', 'want',
    'we', 'when', 'with', 'you', 'your', 'help', 'me', 'i',
})
FENCE_RE = re.compile(r'^\s*(`{3,}|~{3,})')
INLINE_CODE_RE = re.compile(r'``[^`]*``|`[^`]*`')
LINK_RE = re.compile(r'!?\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')

# Anthropic's limits for a skill ("Skill authoring best practices", platform.claude.com); the
# writing-for-agents skill states them in SKILL-MECHANICS.md.
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1024
MAX_BODY_LINES = 500
RESERVED_NAME_WORDS = ('anthropic', 'claude')
CONTENTS_OVER_LINES = 100  # a longer reference file opens with a contents list
CONTENTS_WITHIN_LINES = 30  # "opens with": room for the title and an intro paragraph above it
NAME_RE = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
TAG_RE = re.compile(r'</?[A-Za-z][^<>]*>')
# A quoted trigger ("grill me") is the user's words, not the description's point of view.
QUOTED_RE = re.compile(r'"[^"]*"|(?<!\w)\'[^\']*\'(?!\w)|`[^`]*`')
FIRST_SECOND_PERSON_RE = re.compile(r"\b(I|[Mm]e|[Mm]y|[Ww]e|[Oo]ur|[Yy]ou|[Yy]our)\b")
CONTENTS_RE = re.compile(r'^#{1,6}\s+(?:table of )?contents\b', re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r'\b[\w.-]+\\[\w.-]+\.(?:py|sh|md|json|ts|js)\b')
NOTICE_FILES = ('CREDITS.md',)  # an author's notices beside LICENSE: not reference to point at
# Reference files of skills pinned in skills.lock that miss a packaging rule. Fixing one is a local
# edit to re-apply at every upstream refresh, so each waits here for that call; the test fails when
# an entry stops being true.
KNOWN_UPSTREAM_GAPS = {'unpointed': set(), 'no contents': set()}  # none waiting: the five were fixed here


def parse_frontmatter(text):
    """Parse SKILL.md YAML frontmatter; raise ValueError on missing closing --- or duplicate keys."""
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('missing opening ---')
    try:
        end = lines.index('---', 1)
    except ValueError as err:
        raise ValueError('missing closing ---') from err
    fm_lines = lines[1:end]
    fields = {}
    block_key = None
    block_lines = []
    for line in fm_lines:
        if not line.strip():
            continue
        if line.startswith((' ', '\t')):
            if block_key is not None:
                block_lines.append(line.strip())
            continue
        if block_key is not None:
            fields[block_key] = ' '.join(block_lines).strip()
            block_key = None
            block_lines = []
        if line.lstrip().startswith('#'):
            continue
        key, sep, raw = line.partition(':')
        if not sep:
            raise ValueError(f'malformed frontmatter line: {line!r}')
        key = key.strip()
        if key in fields:
            raise ValueError(f'duplicate frontmatter key: {key}')
        val = raw.strip()
        if val in ('|', '>', '|-', '>-'):
            block_key = key
            fields[key] = ''
        else:
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            fields[key] = val
    if block_key is not None:
        fields[block_key] = ' '.join(block_lines).strip()
    return fields, fm_lines


def broken_relative_links(md_path):
    """Return [(lineno, target)] for relative Markdown links in md_path whose target does not exist."""
    broken = []
    fence = None
    for lineno, line in enumerate(md_path.read_text().splitlines(), 1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            continue
        if fence is not None:
            continue
        cleaned = INLINE_CODE_RE.sub('', line)
        for match in LINK_RE.finditer(cleaned):
            target = match.group(1)
            if target.startswith(('http://', 'https://', 'mailto:', '#')) or '<' in target or '>' in target:
                continue
            path_part = target.split('#', 1)[0]
            if not path_part:
                continue
            if not (md_path.parent / path_part).resolve().exists():
                broken.append((lineno, target))
    return broken


def _tokenize(text):
    return [tok for tok in re.split(r'[^a-z0-9]+', text.lower()) if len(tok) > 2 and tok not in STOPWORDS]


def label(folder):
    """A skill folder's path in the repo, without the skills/ every one but a feature's starts with."""
    return folder.relative_to(skills.WORKSPACE).as_posix().removeprefix('skills/')


def model_invoked_descriptions(workspace):
    """{name: description} for the skills an agent can fire itself (no disable-model-invocation: true)."""
    found = {}
    for name, folder in sorted(skills.repo_skills(workspace).items()):
        fields, _ = parse_frontmatter((folder / 'SKILL.md').read_text())
        if fields.get('disable-model-invocation', '').lower() != 'true':
            found[name] = fields['description']
    return found


def description_collisions(items, threshold=COLLISION_THRESHOLD):
    """Return [(cosine, name_a, name_b)] for pairs at or above threshold under stdlib TF-IDF.

    Only the descriptions are scored; names are labels. Counting name tokens as well would let one
    description under two different names score below the threshold.
    """
    docs = {}
    df = {}
    for name, description in items.items():
        tf = {}
        for tok in _tokenize(description):
            tf[tok] = tf.get(tok, 0) + 1
        docs[name] = tf
        for tok in tf:
            df[tok] = df.get(tok, 0) + 1
    n = len(docs)
    vectors = {}
    for name, tf in docs.items():
        vec = {tok: count * math.log(1 + n / (1 + df[tok])) for tok, count in tf.items()}
        norm = math.sqrt(sum(val * val for val in vec.values()))
        vectors[name] = (vec, norm)
    collisions = []
    names = sorted(vectors)
    for i, a in enumerate(names):
        vec_a, norm_a = vectors[a]
        if not norm_a:
            continue
        for b in names[i + 1:]:
            vec_b, norm_b = vectors[b]
            if not norm_b:
                continue
            dot = sum(val * vec_b[tok] for tok, val in vec_a.items() if tok in vec_b)
            score = dot / (norm_a * norm_b)
            if score >= threshold:
                collisions.append((score, a, b))
    return sorted(collisions, reverse=True)


def frontmatter_problems(fields):
    """What a skill's name and description break of Anthropic's limits, one message each.

    Point of view and the "when" are asked only of a description an agent reads to choose the skill.
    """
    name, description = fields.get('name', ''), fields.get('description', '')
    problems = []
    if len(name) > MAX_NAME_CHARS or not NAME_RE.fullmatch(name):
        problems.append(f'name is not {MAX_NAME_CHARS} or fewer lowercase letters, digits and hyphens')
    problems += [f'name holds the reserved word {word}' for word in RESERVED_NAME_WORDS if word in name]
    if len(description) > MAX_DESCRIPTION_CHARS:
        problems.append(f'description is {len(description)} characters (limit {MAX_DESCRIPTION_CHARS})')
    tags = TAG_RE.findall(description)
    if tags:
        problems.append(f'description holds XML-like tags {tags}: write a placeholder as an example value')
    if fields.get('disable-model-invocation', '').lower() != 'true':
        person = sorted(set(FIRST_SECOND_PERSON_RE.findall(QUOTED_RE.sub(' ', description))))
        if person:
            problems.append(f'description is not in the third person: {person}')
        if not re.search(r'\bwhen\b', description, re.IGNORECASE):
            problems.append('description does not say when to use the skill')
    return problems


def reference_files(folder):
    """The Markdown a skill discloses behind SKILL.md: every .md but SKILL.md and the notices."""
    return sorted(path for path in folder.rglob('*.md') if path.name not in ('SKILL.md', *NOTICE_FILES))


def unpointed_references(folder):
    """Reference files SKILL.md never names: by path, by file name or by folder ('templates/')."""
    text = (folder / 'SKILL.md').read_text()
    missing = []
    for path in reference_files(folder):
        rel = path.relative_to(folder)
        pointers = [rel.as_posix(), path.name, *(f'{parent.as_posix()}/' for parent in rel.parents if parent.parts)]
        if not any(pointer in text for pointer in pointers):
            missing.append(rel.as_posix())
    return missing


def missing_contents(folder):
    """Reference files over CONTENTS_OVER_LINES lines with no Contents heading near the top."""
    missing = []
    for path in reference_files(folder):
        lines = path.read_text().splitlines()
        if len(lines) > CONTENTS_OVER_LINES and not any(map(CONTENTS_RE.match, lines[:CONTENTS_WITHIN_LINES])):
            missing.append(path.relative_to(folder).as_posix())
    return missing


class InstallSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skills 空間 ')
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = self.root / 'repo'
        for name in ('alpha', 'beta'):
            (self.repo / 'skills' / name).mkdir(parents=True)
            (self.repo / 'skills' / name / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
        (self.repo / 'skills/notes').mkdir()  # no SKILL.md, so not a skill
        self.command = self.home / skills.BIN / 'ai-dotfiles'
        self.daily_log = self.home / skills.BIN / 'daily-log'
        self.extension = self.home / where('pi', 'extensions') / skills.PI_EXTENSION

    def tearDown(self):
        self.temp.cleanup()

    def install(self, clis=CLIS, apply=False, uninstall=False, repo=None, path_env=''):
        out = io.StringIO()
        with redirect_stdout(out):
            count = skills.install(self.home, clis, repo or self.repo, apply, uninstall, path_env)
        self.output = out.getvalue()
        return count

    def links(self):
        """{path below home: target} of every link in the folders this step writes."""
        found = {}
        for folder in (*ROOTS, skills.BIN, where('pi', 'extensions')):
            if (self.home / folder).is_dir():
                found.update({str(p.relative_to(self.home)): os.readlink(p)
                              for p in (self.home / folder).iterdir() if p.is_symlink()})
        return found

    def skill_links(self):
        return {path: target for path, target in self.links().items() if '/skills/' in path}

    def test_a_cloud_install_leaves_out_the_local_only_skills_and_their_commands(self):
        """A cloud session's VM gets every skill but config/cloud.json's local_only, and no command
        named after one (daily-log)."""
        (self.repo / 'skills/daily-log').mkdir()
        (self.repo / 'skills/daily-log/SKILL.md').write_text('---\nname: daily-log\n---\n')
        (self.repo / 'config').mkdir()
        (self.repo / 'config/cloud.json').write_text(json.dumps(
            {'version': 1, 'local_only': {'beta': 'needs the Mac', 'daily-log': 'needs the Mac'}}))
        self.assertEqual(sorted(skills.cloud_skills(self.repo)), ['alpha'])
        out = io.StringIO()
        with redirect_stdout(out):
            skills.install(self.home, ['claude'], self.repo, apply=True, path_env='', cloud=True)
        claude = where('claude', 'skills')
        self.assertEqual(sorted(p for p in self.links() if p.startswith(claude)), [f'{claude}/alpha'])
        self.assertTrue(self.command.is_symlink())
        self.assertFalse(self.daily_log.exists())

    def test_the_repo_has_what_the_links_point_at(self):
        for target in (*skills.COMMANDS.values(), skills.PI_EXTENSION_TARGET):
            self.assertTrue((skills.WORKSPACE / target).is_file(), target)

    def test_from_a_linked_worktree_skills_are_read_there_and_linked_into_the_main_checkout(self):
        live = self.root / 'main checkout'
        (self.repo / 'skills/gamma').mkdir()  # new in the worktree, not merged yet
        (self.repo / 'skills/gamma/SKILL.md').write_text('---\nname: gamma\n---\n')
        self.extension.parent.parent.mkdir(parents=True)  # Pi is set up
        with redirect_stdout(io.StringIO()):
            skills.install(self.home, CLIS, self.repo, True, False, '', live=live)
        links = self.links()
        self.assertIn(str(live / 'skills/gamma'), links.values())
        self.assertEqual(links[f'{skills.BIN}/ai-dotfiles'], str(live / 'scripts/ai-dotfiles'))
        self.assertEqual(links[str(self.extension.relative_to(self.home))], str(live / skills.PI_EXTENSION_TARGET))
        self.assertEqual([t for t in links.values() if not t.startswith(f'{live}/')], [])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(skills.install(self.home, CLIS, self.repo, False, False, '', live=live), 0)

    def test_a_bundle_is_flattened_and_a_clash_refused(self):
        (self.repo / 'skills/git/push-branch').mkdir(parents=True)
        (self.repo / 'skills/git/push-branch/SKILL.md').write_text('---\nname: push-branch\n---\n')
        (self.repo / 'skills/git/scripts').mkdir()  # the bundle's shared code: not a skill
        found = skills.skills(self.repo / 'skills')
        self.assertEqual(sorted(found), ['alpha', 'beta', 'push-branch'])
        self.install(apply=True)
        self.assertEqual(os.readlink(self.home / '.claude/skills/push-branch'), str(self.repo / 'skills/git/push-branch'))
        (self.repo / 'skills/git/alpha').mkdir()
        (self.repo / 'skills/git/alpha/SKILL.md').write_text('---\nname: alpha\n---\n')
        with self.assertRaisesRegex(ValueError, 'Two skills named alpha'):
            skills.skills(self.repo / 'skills')

    def test_a_feature_folder_holds_a_skill_and_a_name_clash_across_folders_is_refused(self):
        def skill(folder):
            (self.repo / folder).mkdir(parents=True)
            (self.repo / folder / 'SKILL.md').write_text(f'---\nname: {folder.rsplit("/", 1)[1]}\n---\n')
        skill('features/gate/gate')  # a feature with its own skill one folder down
        skill('features/solo')       # a feature whose folder is the skill
        (self.repo / 'features/gate/scripts').mkdir()
        (self.repo / 'features/solo/tests').mkdir()
        self.assertEqual(sorted(skills.repo_skills(self.repo)), ['alpha', 'beta', 'gate', 'solo'])
        self.install(apply=True)
        self.assertEqual(os.readlink(self.home / '.claude/skills/solo'), str(self.repo / 'features/solo'))
        self.assertEqual(os.readlink(self.home / '.claude/skills/gate'), str(self.repo / 'features/gate/gate'))
        skill('features/alpha')
        with self.assertRaisesRegex(ValueError, 'Two skills named alpha'):
            skills.repo_skills(self.repo)

    def test_repo_skills_are_valid(self):
        names = skills.repo_skills(skills.WORKSPACE)
        self.assertIn('grilling', names)
        for name, folder in names.items():
            text = (folder / 'SKILL.md').read_text()
            self.assertTrue(text.startswith(f'---\nname: {name}\n'), name)
            self.assertNotRegex(text, r'/Users/|/opt/homebrew')
            fields, fm_lines = parse_frontmatter(text)
            self.assertTrue(fields.get('description', '').strip(), f'{name}: empty description')
            # Strict YAML (Pi) rejects ': ' or ' #' inside an unquoted value.
            for line in fm_lines:
                key, _, value = line.partition(': ')
                if value[:1] not in ('"', "'", '|', '>'):
                    self.assertNotRegex(value, r': | #|:$', f'{name}: quote {key}')

    def test_dry_run_then_apply_links_every_root_once(self):
        self.assertEqual(self.install(), 9)  # six skill links, the two commands, and the receipt
        self.assertEqual(self.links(), {})
        self.assertFalse((self.home / '.local').exists())
        self.install(apply=True)
        self.assertEqual(len(self.skill_links()), 6)
        for root in ROOTS:
            self.assertEqual((self.home / root / 'alpha').resolve(), self.repo / 'skills/alpha')
            self.assertFalse((self.home / root / 'notes').exists())
        self.assertEqual(os.readlink(self.command), str(self.repo / 'scripts/ai-dotfiles'))
        # The test repo has no daily-log skill: a link does not need its target to exist.
        self.assertEqual(os.readlink(self.daily_log), str(self.repo / 'skills/daily-log/scripts/daily_log.py'))
        self.assertFalse(self.extension.is_symlink())  # Pi is not set up here
        self.assertEqual(self.install(), 0)

    def test_refuses_an_entry_it_did_not_create(self):
        (self.home / '.agents/skills/beta').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(apply=True)
        self.assertEqual(self.links(), {})
        (self.home / '.agents/skills/beta').rmdir()
        for command in (self.command, self.daily_log):
            with self.subTest(command.name):
                command.parent.mkdir(parents=True, exist_ok=True)
                command.symlink_to(self.root / 'elsewhere')
                with self.assertRaisesRegex(ValueError, 'refusing'):
                    self.install(apply=True)
                self.assertEqual(self.skill_links(), {})
                command.unlink()

    def test_removed_skill_link_goes_but_a_user_change_stays(self):
        self.install(apply=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        mine = self.home / '.claude/skills/alpha'
        mine.unlink()
        mine.symlink_to(elsewhere, target_is_directory=True)
        (self.repo / 'skills/alpha/SKILL.md').unlink()
        (self.repo / 'skills/beta/SKILL.md').unlink()
        self.install(apply=True)
        self.assertEqual(self.skill_links(), {'.claude/skills/alpha': str(elsewhere)})
        self.assertEqual(self.install(), 0)

    def test_target_selection_leaves_other_roots_alone(self):
        self.install(('claude',), apply=True)
        self.assertEqual(sorted(self.skill_links()), ['.claude/skills/alpha', '.claude/skills/beta'])
        self.install(('codex',), apply=True)  # Codex and Pi share one folder
        self.install(('agy',), apply=True)
        self.assertEqual(len(self.skill_links()), 6)
        self.assertEqual(self.install(('claude', 'pi', 'agy')), 0)

    def test_uninstall_removes_only_owned_links(self):
        self.install(apply=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        mine = self.home / '.claude/skills/alpha'
        mine.unlink()
        mine.symlink_to(elsewhere, target_is_directory=True)
        (self.home / '.agents/skills/user-skill').mkdir()
        self.assertEqual(self.install(uninstall=True), 8)  # five skill links, the two commands, the receipt
        self.assertEqual(len(self.skill_links()), 6)  # dry-run removed nothing
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {'.claude/skills/alpha': str(elsewhere)})
        self.assertTrue((self.home / '.agents/skills/user-skill').is_dir())
        self.assertEqual(self.install(uninstall=True), 0)

    def test_uninstall_one_cli_keeps_other_roots_and_the_command(self):
        self.install(apply=True)
        self.install(('claude',), apply=True, uninstall=True)
        self.assertEqual(len(self.skill_links()), 4)
        self.assertNotIn('.claude/skills/alpha', self.links())
        self.assertTrue(self.command.is_symlink())  # the commands serve the other CLIs
        self.assertTrue(self.daily_log.is_symlink())
        self.assertEqual(self.install(), 3)  # reinstall relinks claude and records them
        self.install(apply=True)
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {})

    def test_matching_command_links_are_adopted_and_the_old_receipt_goes(self):
        # As install-command.py left the first one before this step linked the commands.
        self.command.parent.mkdir(parents=True)
        self.command.symlink_to(self.repo / 'scripts/ai-dotfiles')
        old = self.home / skills.COMMAND_RECEIPT
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({'version': 1, 'link': str(self.command), 'target': os.readlink(self.command)}))
        self.daily_log.symlink_to(self.repo / 'skills/daily-log/scripts/daily_log.py')
        self.assertEqual(self.install(('claude',), apply=True), 4)  # alpha, beta, both receipts
        owned = json.loads((self.home / skills.RECEIPT).read_text())['links']
        self.assertEqual(owned[str(self.command)], str(self.repo / 'scripts/ai-dotfiles'))
        self.assertEqual(owned[str(self.daily_log)], str(self.repo / 'skills/daily-log/scripts/daily_log.py'))
        self.assertFalse(old.exists())
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {})

    def test_an_owned_link_to_a_skill_from_outside_the_repo_goes(self):
        # zkfy's query was linked by this step until the knowledge step was dropped.
        self.install(apply=True)
        outside = self.root / 'zkfy/skills/query'
        outside.mkdir(parents=True)
        query = self.home / '.claude/skills/query'
        query.symlink_to(outside, target_is_directory=True)
        receipt = self.home / skills.RECEIPT
        data = json.loads(receipt.read_text())
        data['links'][str(query)] = str(outside)
        receipt.write_text(json.dumps(data))
        self.assertEqual(self.install(apply=True), 2)  # the link and the receipt
        self.assertFalse(query.is_symlink())
        self.assertEqual(self.install(), 0)

    def test_command_path_hint_and_moved_repo(self):
        self.install()
        self.assertIn('Hint: add', self.output)
        self.assertIn('ai-dotfiles and daily-log', self.output)
        self.install(path_env=f'/usr/bin{os.pathsep}{self.command.parent}/')
        self.assertNotIn('Hint', self.output)
        self.install(apply=True)
        moved = self.root / 'moved'
        self.repo.rename(moved)
        self.assertEqual(self.install(('claude',), apply=True, repo=moved), 5)  # alpha, beta, the commands, receipt
        self.assertEqual(os.readlink(self.command), str(moved / 'scripts/ai-dotfiles'))
        self.assertEqual(os.readlink(self.daily_log), str(moved / 'skills/daily-log/scripts/daily_log.py'))

    def test_the_retired_daily_log_extension_is_removed(self):
        (self.home / '.pi/agent').mkdir(parents=True)
        self.install(('pi',), apply=True)
        old = self.extension.parent / 'ai-dotfiles-daily-log.ts'
        target = str(self.repo / 'skills/daily-log/hooks/daily-log.ts')
        old.symlink_to(target)
        receipt = self.home / skills.RECEIPT
        data = json.loads(receipt.read_text())
        data['links'][str(old)] = target
        receipt.write_text(json.dumps(data))
        self.assertEqual(self.install(('pi',), apply=True), 2)  # the old link, the receipt
        self.assertFalse(old.is_symlink())
        self.assertTrue(self.extension.is_symlink())

    def test_pi_extension_follows_pi(self):
        self.install(('pi',), apply=True)
        self.assertFalse(self.extension.is_symlink())  # Pi is not set up here yet
        (self.home / '.pi/agent').mkdir(parents=True)
        self.install(('claude',), apply=True)
        self.assertFalse(self.extension.is_symlink())
        self.install(('pi',), apply=True)
        self.assertEqual(os.readlink(self.extension), str(self.repo / 'scripts/agent_hooks.ts'))
        self.install(('claude',), apply=True, uninstall=True)
        self.assertTrue(self.extension.is_symlink())
        self.install(('pi',), apply=True, uninstall=True)
        self.assertFalse(self.extension.is_symlink())
        self.extension.write_text('// mine')
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('pi',))

    def folder(self, root):
        return sorted(path for path in self.skill_links() if path.startswith(root))

    def test_a_cli_switched_off_loses_its_links_but_a_shared_folder_stays(self):
        (self.home / '.pi/agent').mkdir(parents=True)
        self.install(apply=True)
        self.assertTrue(self.extension.is_symlink())
        with patch.object(installer, 'REGISTRY', registry(self.root, agy=False, codex=False)):
            self.install(apply=True)
            self.assertTrue(self.extension.is_symlink())  # Pi is still on
            self.assertEqual(self.folder('.gemini/'), [])
            self.assertEqual(len(self.folder('.agents/')), 2)  # Pi, still on, reads it too
            self.assertEqual(self.install(), 0)
        with patch.object(installer, 'REGISTRY', registry(self.root, pi=False)):
            self.install(apply=True)
            self.assertFalse(self.extension.is_symlink())
            self.assertEqual(len(self.folder('.agents/')), 2)  # Codex, on again, reads it
            self.install(('codex',), apply=True, uninstall=True)
            self.assertEqual(self.folder('.agents/'), [])  # no CLI that is on reads it now

    def test_uninstalling_one_cli_keeps_a_folder_another_cli_reads(self):
        self.install(apply=True)
        self.install(('codex',), apply=True, uninstall=True)
        self.assertEqual(len(self.folder('.agents/')), 2)  # Pi is on and reads ~/.agents/skills
        self.install(('codex', 'pi'), apply=True, uninstall=True)
        self.assertEqual(self.folder('.agents/'), [])


class SkillQualityTest(unittest.TestCase):
    def test_repo_skills_pass_size_hygiene_and_link_checks(self):
        names = skills.repo_skills(skills.WORKSPACE)
        disallowed = sorted(
            str(path.relative_to(skills.WORKSPACE))
            for top in skills.SKILL_FOLDERS
            for pattern in DISALLOWED_SKILL_FILES
            for path in (skills.WORKSPACE / top).rglob(pattern)
        )
        self.assertEqual(disallowed, [], f'disallowed scratch files in skills/: {disallowed}')
        for name, folder in sorted(names.items()):
            skill_md = folder / 'SKILL.md'
            size = skill_md.stat().st_size
            self.assertLess(size, MAX_SKILL_BYTES, f'{name}/SKILL.md is {size} bytes (limit {MAX_SKILL_BYTES})')
            for md in sorted(folder.rglob('*.md')):
                broken = broken_relative_links(md)
                self.assertEqual(broken, [], f'{md.relative_to(skills.WORKSPACE)} has broken links: {broken}')

    def test_repo_skills_keep_the_frontmatter_and_body_limits(self):
        for name, folder in sorted(skills.repo_skills(skills.WORKSPACE).items()):
            text = (folder / 'SKILL.md').read_text()
            fields, fm_lines = parse_frontmatter(text)
            self.assertEqual(frontmatter_problems(fields), [], name)
            body = len(text.splitlines()) - len(fm_lines) - 2  # less the two --- lines
            self.assertLess(body, MAX_BODY_LINES, f'{name}/SKILL.md body is {body} lines (limit {MAX_BODY_LINES})')

    def test_repo_reference_files_are_pointed_at_and_open_with_contents(self):
        skills_root = skills.WORKSPACE / 'skills'
        found = {'unpointed': set(), 'no contents': set()}
        for name, folder in sorted(skills.repo_skills(skills.WORKSPACE).items()):
            prefix = label(folder)
            found['unpointed'].update(f'{prefix}/{rel}' for rel in unpointed_references(folder))
            found['no contents'].update(f'{prefix}/{rel}' for rel in missing_contents(folder))
            for md in sorted(folder.rglob('*.md')):
                self.assertNotRegex(md.read_text(), WINDOWS_PATH_RE, f'{md.relative_to(skills.WORKSPACE)}: use forward slashes')
        self.assertEqual(found, KNOWN_UPSTREAM_GAPS)  # a new gap, or a known one that was fixed
        pinned = json.loads((skills_root / 'skills.lock').read_text())['skills']
        for gap in sorted(set().union(*KNOWN_UPSTREAM_GAPS.values())):
            self.assertIn(gap.split('/')[0], pinned, f'{gap}: only a pinned skill may wait in KNOWN_UPSTREAM_GAPS')

    def test_frontmatter_problems_name_each_broken_limit(self):
        good = {'name': 'pdf-processing', 'description': 'Extracts text from PDFs. Use when the user says "help me".'}
        self.assertEqual(frontmatter_problems(good), [])
        self.assertEqual(frontmatter_problems({**good, 'description': "Lands the user's 'approve 57' when asked."}), [])
        for fields, expected in (
            ({**good, 'name': 'PDF_tools'}, 'lowercase letters, digits and hyphens'),
            ({**good, 'name': 'p' * (MAX_NAME_CHARS + 1)}, 'lowercase letters, digits and hyphens'),
            ({**good, 'name': 'claude-helper'}, 'reserved word claude'),
            ({**good, 'description': 'x when ' * 200}, f'limit {MAX_DESCRIPTION_CHARS}'),
            ({**good, 'description': 'Tags archive/<name> when a branch goes.'}, "XML-like tags ['<name>']"),
            ({**good, 'description': 'Use when you need a PDF read.'}, "third person: ['you']"),
            ({**good, 'description': 'Extracts text from PDFs.'}, 'does not say when'),
        ):
            with self.subTest(expected):
                self.assertTrue(any(expected in problem for problem in frontmatter_problems(fields)))
        by_hand = {'name': 'router', 'description': 'Ask which skill fits your work.', 'disable-model-invocation': 'true'}
        self.assertEqual(frontmatter_problems(by_hand), [])  # a human reads it: no point of view, no "when"

    def test_reference_checks_find_the_unpointed_file_and_the_long_one_without_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'templates').mkdir()
            (folder / 'SKILL.md').write_text('See [forms](FORMS.md) and `templates/<type>.md`.\n')
            long_text = '# Title\n' + 'line\n' * CONTENTS_OVER_LINES
            (folder / 'FORMS.md').write_text(long_text.replace('# Title\n', '# Title\n\n## Contents\n', 1))
            (folder / 'templates/memo.md').write_text(long_text)
            (folder / 'STRAY.md').write_text('# short\n')
            (folder / 'CREDITS.md').write_text('# thanks\n')
            self.assertEqual(unpointed_references(folder), ['STRAY.md'])
            self.assertEqual(missing_contents(folder), ['templates/memo.md'])

    def test_model_invoked_descriptions_do_not_collide(self):
        model_invoked = model_invoked_descriptions(skills.WORKSPACE)
        self.assertGreater(len(model_invoked), 0)
        self.assertNotIn('implement-spec', model_invoked)  # disable-model-invocation: true excluded
        collisions = description_collisions(model_invoked, threshold=COLLISION_THRESHOLD)
        self.assertEqual(
            collisions,
            [],
            f'model-invoked skill description collisions >= {COLLISION_THRESHOLD}: {collisions}',
        )

    def test_collision_check_flags_a_copy_of_any_real_description(self):
        model_invoked = model_invoked_descriptions(skills.WORKSPACE)
        for name, description in model_invoked.items():
            with self.subTest(skill=name):
                hits = description_collisions({**model_invoked, 'zz-copy': description})
                self.assertIn((name, 'zz-copy'), [(a, b) for _, a, b in hits])  # 'zz-' sorts last

    def test_parse_frontmatter_checks_closing_fence_duplicates_and_blocks(self):
        with self.assertRaisesRegex(ValueError, 'missing closing ---'):
            parse_frontmatter('---\nname: demo\ndescription: hi\n')
        with self.assertRaisesRegex(ValueError, 'duplicate frontmatter key: description'):
            parse_frontmatter('---\nname: demo\ndescription: one\ndescription: two\n---\n')
        fields, _ = parse_frontmatter(
            '---\nname: demo\ndescription: >\n  first line\n  second line\nmetadata:\n  author: test\n---\n'
        )
        self.assertEqual(fields['description'], 'first line second line')

    def test_broken_relative_links_catches_missing_and_ignores_fences_code_and_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'EXISTS.md').write_text('# ok\n')
            md = folder / 'SKILL.md'
            md.write_text(
                'See [ok](EXISTS.md#heading), [web](https://example.com), [anchor](#local),\n'
                'inline `[fake](NOPE.md)` and [placeholder](<path>), plus [bad](MISSING.md).\n'
                '```markdown\n[fenced](ALSO_MISSING.md)\n```\n'
            )
            self.assertEqual(broken_relative_links(md), [(2, 'MISSING.md')])

    def test_description_collisions_flag_one_description_under_two_names(self):
        same = 'Review pull request diffs against coding standards and spec requirements.'
        items = {
            'spec-audit': same,
            'diff-check': same,
            'daily-log': 'Record finished engineering work in the daily log journal file.',
        }
        hits = description_collisions(items, threshold=COLLISION_THRESHOLD)
        self.assertEqual([(a, b) for _, a, b in hits], [('diff-check', 'spec-audit')])
        self.assertAlmostEqual(hits[0][0], 1.0)


if __name__ == '__main__':
    unittest.main()
