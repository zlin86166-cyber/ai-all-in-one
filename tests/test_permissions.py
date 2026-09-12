from __future__ import annotations

import unittest
from argparse import Namespace

from desktop import _max_control_requested


class PermissionModeTests(unittest.TestCase):
    def test_normal_desktop_launch_defaults_to_max_control(self):
        self.assertTrue(_max_control_requested(Namespace(
            max_control=False, safe_mode=False, self_test=False
        )))

    def test_safe_mode_is_explicitly_limited(self):
        self.assertFalse(_max_control_requested(Namespace(
            max_control=False, safe_mode=True, self_test=False
        )))

    def test_self_test_stays_non_interactive_by_default(self):
        self.assertFalse(_max_control_requested(Namespace(
            max_control=False, safe_mode=False, self_test=True
        )))

    def test_explicit_max_control_wins(self):
        self.assertTrue(_max_control_requested(Namespace(
            max_control=True, safe_mode=True, self_test=False
        )))


if __name__ == "__main__":
    unittest.main()
