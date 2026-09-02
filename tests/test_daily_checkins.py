import unittest

import prompts


class DailyPromptTests(unittest.TestCase):
    def test_daily_prompts_are_short_one_tap_questions(self):
        self.assertGreaterEqual(len(prompts.DAILY_PROMPTS), 10)
        for prompt in prompts.DAILY_PROMPTS:
            self.assertLessEqual(len(prompt.question), 60)
            self.assertGreaterEqual(len(prompt.options), 2)
            self.assertTrue(all(option.id and option.label for option in prompt.options))
            self.assertNotIn("song", prompt.question.lower())
            self.assertNotIn("recommend", prompt.question.lower())

    def test_daily_message_shows_anonymous_totals_and_clickable_callout(self):
        prompt = prompts.get_daily_prompt("coffee_or_tea")
        member = type("Member", (), {"user_id": 7, "name": "Alex"})()

        message = prompts.format_daily_message(prompt, {"coffee": 2}, [member])

        self.assertIn("Anonymous totals", message)
        self.assertIn("Coffee: 2", message)
        self.assertIn('tg://user?id=7', message)
        self.assertNotIn("Alex selected", message)

    def test_prompt_ids_do_not_repeat_until_the_bank_is_exhausted(self):
        prompt_ids = prompts.daily_prompt_ids()
        used = set()

        for _ in prompt_ids:
            selected = prompts.choose_daily_prompt_id(used)
            self.assertNotIn(selected, used)
            used.add(selected)

        self.assertEqual(used, set(prompt_ids))
        self.assertIn(prompts.choose_daily_prompt_id(used), prompt_ids)

if __name__ == "__main__":
    unittest.main()
