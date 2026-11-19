"""herdr-title: an agent's row in Herdr says what its current prompt is for.

Run: python3 -m unittest discover -s scripts/tests -p 'test_herdr_title.py' -v
"""
import json
import unittest

from support import ROOT, load


class ConfigTest(unittest.TestCase):
    """config/herdr-title.json: the tags, and what decides one at once."""

    def setUp(self):
        self.config = json.loads((ROOT / 'config/herdr-title.json').read_text())

    def test_every_tag_has_a_form_for_working_and_one_for_done_that_fit_the_sidebar(self):
        self.assertEqual(len(self.config['tags']), 10)
        for tag, forms in self.config['tags'].items():
            self.assertTrue(forms['working'].endswith('ING') and forms['done'].endswith('ED'), tag)
            self.assertTrue(forms['working'].startswith(tag[:3]) and forms['done'].startswith(tag[:3]), tag)
            self.assertLessEqual(max(len(forms['working']), len(forms['done'])), 11, tag)  # 26 columns in all
            self.assertTrue(forms['means'].strip(), tag)

    def test_every_skill_and_command_leads_to_a_tag(self):
        for table in ('skills', 'outside', 'commands'):
            self.assertEqual(sorted(set(self.config[table].values()) - set(self.config['tags'])), [], table)

    def test_skills_are_this_repos_and_outside_holds_the_rest(self):
        ours = set(load('install/skills.py').skills(ROOT / 'skills'))  # bundles (skills/git/) flattened
        self.assertEqual(sorted(set(self.config['skills']) - ours), [], 'named under skills, not in skills/')
        self.assertEqual(sorted(set(self.config['outside']) & ours), [], 'a skill of this repo under outside')


if __name__ == '__main__':
    unittest.main()
