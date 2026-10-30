import re
import unittest

from support import ROOT

TUTOR = ROOT / 'skills' / 'tutor' / 'SKILL.md'
STYLE = ROOT / 'skills' / 'house-style' / 'STYLE.md'
TEMPLATE = re.compile(r'"([^"]+)" template')


def frontmatter(text):
    head = text.split('---', 2)[1].strip().splitlines()
    return {k.strip(): v.strip() for k, v in (line.split(':', 1) for line in head)}


class TutorTest(unittest.TestCase):
    """The tutor skill stays hand-invoked and its template stays in house-style."""

    def test_template_is_a_house_style_heading(self):
        names = TEMPLATE.findall(TUTOR.read_text())
        self.assertTrue(names, 'tutor names no house-style template')
        headings = {line[4:] for line in STYLE.read_text().splitlines() if line.startswith('### ')}
        self.assertEqual(sorted(set(names) - headings), [], 'templates missing from STYLE.md')

    def test_hand_invoked_with_argument_hint(self):
        fm = frontmatter(TUTOR.read_text())
        self.assertEqual(fm.get('disable-model-invocation'), 'true')
        self.assertIn('argument-hint', fm)


if __name__ == '__main__':
    unittest.main()
