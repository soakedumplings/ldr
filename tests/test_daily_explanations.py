import unittest

from db import DB
import prompts


class DailyExplanationTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:")
        self.db.register_group(100, "Friends")
        self.db.upsert_member(7, "Alex", "Asia/Singapore")
        self.db.upsert_member(8, "Blair", "Asia/Singapore")
        self.db.add_membership(100, 7)
        self.db.add_membership(100, 8)
        self.db.record_daily_prompt(100, "2026-09-03", "feeling_today")
        self.db.record_daily_response(
            100, 7, "2026-09-03", "feeling_today", "tired"
        )
        self.db.record_daily_response(
            100, 8, "2026-09-03", "feeling_today", "calm"
        )
        self.db.record_daily_explanation_poll(
            100, "2026-09-03", 501, 502, "2026-09-03T21:00:00+08:00"
        )

    def tearDown(self):
        self.db.close()

    def test_only_daily_respondents_are_eligible(self):
        respondents = self.db.daily_respondents(100, "2026-09-03")

        self.assertEqual([person.user_id for person in respondents], [7, 8])
        self.assertEqual(respondents[0].option_id, "tired")

    def test_explanation_vote_can_change_and_counts_move(self):
        self.assertTrue(self.db.record_explanation_vote(100, "2026-09-03", 7, 7))
        self.assertTrue(self.db.record_explanation_vote(100, "2026-09-03", 8, 7))
        self.assertEqual(self.db.explanation_vote_counts(100, "2026-09-03"), {7: 2})

        self.assertTrue(self.db.record_explanation_vote(100, "2026-09-03", 8, 8))
        self.assertEqual(
            self.db.explanation_vote_counts(100, "2026-09-03"), {7: 1, 8: 1}
        )
        self.assertFalse(self.db.record_explanation_vote(100, "2026-09-03", 8, 8))

    def test_explanation_vote_is_rejected_after_three_hour_deadline(self):
        self.assertFalse(
            self.db.record_explanation_vote(
                100,
                "2026-09-03",
                7,
                8,
                "2026-09-03T21:00:00+08:00",
            )
        )

    def test_closing_returns_winner_with_original_answer(self):
        self.db.record_explanation_vote(100, "2026-09-03", 7, 8)
        self.db.record_explanation_vote(100, "2026-09-03", 8, 8)

        winner = self.db.close_daily_explanation_poll(
            100, "2026-09-03", "2026-09-03T21:00:00+08:00"
        )

        self.assertEqual(winner.user_id, 8)
        self.assertEqual(winner.name, "Blair")
        self.assertEqual(winner.option_id, "calm")
        self.assertEqual(winner.vote_count, 2)

    def test_due_polls_are_scoped_to_the_current_group(self):
        self.db.register_group(200, "Other")
        self.db.record_daily_explanation_poll(
            200,
            "2026-09-03",
            601,
            602,
            "2026-09-03T20:00:00+08:00",
        )

        due = self.db.due_daily_explanation_polls(
            100, "2026-09-03T21:00:00+08:00"
        )

        self.assertEqual([poll["chat_id"] for poll in due], [100])

    def test_summary_and_explanation_messages_show_the_relevant_choices(self):
        prompt = prompts.get_daily_prompt("feeling_today")
        respondents = self.db.daily_respondents(100, "2026-09-03")

        summary = prompts.format_daily_summary(prompt, {"tired": 1, "calm": 1})
        poll = prompts.format_explanation_poll(
            prompt, respondents, {7: 1, 8: 0}, "2026-09-03T21:00:00+08:00"
        )

        self.assertIn("Today's check-in", summary)
        self.assertIn("😴 Tired: 1", summary)
        self.assertIn("Who should explain their choice?", poll)
        self.assertIn("Alex", poll)
        self.assertIn("😴 Tired", poll)
        self.assertIn("Voting closes", poll)


if __name__ == "__main__":
    unittest.main()
