from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ai_hub.scheduler import Scheduler
from tools import model_sync


class RegressionTests(unittest.TestCase):
    def test_versioned_server_entry_point_is_importable(self):
        from ai_hub.server_v2 import create_server

        self.assertTrue(callable(create_server))

    def test_scheduler_normalizes_aware_and_naive_timestamps(self):
        now = datetime(2026, 9, 12, 1, 5, tzinfo=timezone.utc)
        self.assertEqual(
            Scheduler._elapsed_since(now, "2026-09-11T23:05:00+00:00"),
            7200,
        )
        self.assertEqual(
            Scheduler._elapsed_since(now, "2026-09-12T00:05:00"),
            3600,
        )

    def test_scheduler_cross_midnight_uses_start_weekday(self):
        next_day = datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc)
        self.assertTrue(
            Scheduler._weekday_in_window(next_day, {0}, "22:00", "02:00")
        )

    def test_model_sync_does_not_treat_tensor_bytes_as_parameter_count(self):
        self.assertIsNone(
            model_sync.parameters_b(
                {"id": "mystery-instruct", "safetensors": {"total": 50_000_000_000}}
            )
        )


if __name__ == "__main__":
    unittest.main()
