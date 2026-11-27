"""lib/install/steps.py: the install steps are one ordered list that install, uninstall, check and --help read."""
import unittest

from support import ROOT
import steps


class StepListTest(unittest.TestCase):
    def test_every_listed_step_is_a_module_with_the_interface(self):
        for name, module in zip(steps.STEPS, steps.load()):
            with self.subTest(step=name):
                self.assertTrue((ROOT / 'lib/install' / f'{name}.py').is_file())
                for text in (module.SUMMARY, module.UNDO):
                    self.assertTrue(text.strip() and '\n' not in text)
                self.assertTrue(callable(module.execute) and callable(module.main))
                self.assertTrue(callable(getattr(module, 'checks', print)))
                self.assertIsInstance(getattr(module, 'CLOUD_SKIP', ''), str)

    def test_no_step_module_is_left_out_of_the_list(self):
        modules = {path.stem for path in (ROOT / 'lib/install').glob('*.py')}
        self.assertEqual(modules - set(steps.STEPS), {'installer', 'steps', 'run'} & modules)

    def test_a_cloud_session_leaves_out_plugins_and_launchd_only(self):
        skipped = [module.__name__ for module in steps.load() if getattr(module, 'CLOUD_SKIP', None)]
        self.assertEqual(skipped, ['plugins', 'launchd'])
        for module in steps.load(skipped):
            self.assertTrue(module.CLOUD_SKIP.startswith(f'{module.__name__}: skipped in a cloud session'))


if __name__ == '__main__':
    unittest.main()
