import unittest

from db import DB


class DailyResponseTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:")
        self.db.register_group(100, "Friends")
        self.db.upsert_member(7, "Alex", "Asia/Singapore")
        self.db.add_membership(100, 7)

    def tearDown(self):
        self.db.close()

    def test_duplicate_taps_only_count_once(self):
        self.db.record_daily_prompt(100, "2026-09-01", "coffee_or_tea")

        first = self.db.record_daily_response(
            100, 7, "2026-09-01", "coffee_or_tea", "coffee"
        )
        duplicate = self.db.record_daily_response(
            100, 7, "2026-09-01", "coffee_or_tea", "tea"
        )

        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertEqual(self.db.daily_response_counts(100, "2026-09-01"), {"coffee": 1})

    def test_two_missed_prompts_trigger_one_callout_until_user_answers(self):
        self.db.record_daily_prompt(100, "2026-09-01", "p1")
        self.db.record_daily_prompt(100, "2026-09-02", "p2")

        first_callout = self.db.prepare_daily_callouts(100, "2026-09-03")
        second_callout = self.db.prepare_daily_callouts(100, "2026-09-03")

        self.assertEqual([member.user_id for member in first_callout], [7])
        self.assertEqual(second_callout, [])

        self.db.record_daily_prompt(100, "2026-09-03", "p3")
        self.assertTrue(
            self.db.record_daily_response(100, 7, "2026-09-03", "p3", "okay")
        )

        self.db.record_daily_prompt(100, "2026-09-04", "p4")
        self.db.record_daily_prompt(100, "2026-09-05", "p5")
        callout_after_return = self.db.prepare_daily_callouts(100, "2026-09-06")

        self.assertEqual([member.user_id for member in callout_after_return], [7])
