import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import scheduler


class DailyScheduleTests(unittest.TestCase):
    def test_summary_and_close_windows_are_singapore_time(self):
        before_summary = datetime(2026, 9, 3, 9, 59, tzinfo=ZoneInfo("UTC"))
        summary_time = datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("UTC"))
        close_time = datetime(2026, 9, 3, 13, 0, tzinfo=ZoneInfo("UTC"))

        self.assertFalse(scheduler.daily_summary_due(before_summary))
        self.assertTrue(scheduler.daily_summary_due(summary_time))
        self.assertEqual(scheduler.singapore_date(summary_time), "2026-09-03")
        self.assertEqual(
            scheduler.daily_explanation_close(summary_time).isoformat(),
            "2026-09-03T21:00:00+08:00",
        )
        self.assertTrue(scheduler.explanation_close_due(close_time))


if __name__ == "__main__":
    unittest.main()
