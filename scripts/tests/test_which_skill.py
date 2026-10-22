import re
import unittest

from support import ROOT

SKILLS = ROOT / 'skills'
ROUTER = SKILLS / 'which-skill'
NAME = re.compile(r'`([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`')


def named(file):
    """Backticked skill-like names in a router file, the attribution line aside."""
    lines = (ROUTER / file).read_text().splitlines()
    return set(NAME.findall('\n'.join(line for line in lines if not line.startswith('Adapted from '))))


class WhichSkillTest(unittest.TestCase):
    """which-skill names every skill in skills/, and only those."""

    def test_routes_every_skill_and_names_no_other(self):
        skills = {p.parent.name for p in SKILLS.glob('*/SKILL.md')} - {'which-skill'}
        found = named('SKILL.md')
        self.assertEqual(sorted(skills - found), [], 'skills which-skill does not route')
        self.assertEqual(sorted(found - skills), [], 'names in which-skill that are not skills')

    def test_phase_boundaries_names_only_skills(self):
        skills = {p.parent.name for p in SKILLS.glob('*/SKILL.md')}
        self.assertEqual(sorted(named('PHASE-BOUNDARIES.md') - skills), [])


if __name__ == '__main__':
    unittest.main()
