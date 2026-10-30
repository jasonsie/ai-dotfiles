import re
import unittest

from support import ROOT

SKILL = ROOT / 'skills' / 'house-style'
TYPE = re.compile(r'^\| `([a-z][a-z0-9]*(?:-[a-z0-9]+)*)` \|', re.M)


class HouseStyleTest(unittest.TestCase):
    """Every template in skills/house-style/templates/ is a type in the SKILL.md table."""

    def test_templates_are_listed_types(self):
        types = set(TYPE.findall((SKILL / 'SKILL.md').read_text()))
        templates = {p.stem for p in (SKILL / 'templates').glob('*.md')}
        self.assertIn('spec', types)
        self.assertEqual(sorted(templates - types), [], 'templates without a row in the type table')


if __name__ == '__main__':
    unittest.main()
