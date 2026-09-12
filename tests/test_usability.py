import unittest
from datetime import datetime
from ai_hub.scheduler import Scheduler


class UsabilityRegressionTests(unittest.TestCase):
    def test_monday_early_morning_belongs_to_sunday(self):
        self.assertFalse(Scheduler._weekday_in_window(
            datetime(2026, 9, 7, 1), {0}, "22:00", "02:00"))

    def test_tuesday_early_morning_belongs_to_monday(self):
        self.assertTrue(Scheduler._weekday_in_window(
            datetime(2026, 9, 8, 1), {0}, "22:00", "02:00"))

    def test_normal_window_uses_current_weekday(self):
        self.assertTrue(Scheduler._weekday_in_window(
            datetime(2026, 9, 7, 10), {0}, "09:00", "17:00"))
