import asyncio
import unittest

import bot


class _FakeChat:
    type = "supergroup"
    id = 100


class _FakeUser:
    id = 7


class _FakeMessage:
    chat = _FakeChat()


class _FakeQuery:
    data = "daily|2026-09-03|coffee_or_tea|coffee"
    message = _FakeMessage()
    from_user = _FakeUser()

    def __init__(self, events):
        self.events = events

    async def answer(self, *args, **kwargs):
        self.events.append(("answer", args, kwargs))

    async def edit_message_text(self, *args, **kwargs):
        self.events.append(("edit", args, kwargs))


class _FakeDB:
    def __init__(self, events):
        self.events = events

    def is_group_member(self, chat_id, user_id):
        self.events.append("is_group_member")
        return True

    def get_daily_prompt(self, chat_id, prompt_date):
        self.events.append("get_daily_prompt")
        return {"prompt_id": "coffee_or_tea"}

    def get_group_state(self, chat_id):
        self.events.append("get_group_state")
        return {"last_daily_date": "2026-09-03"}

    def record_daily_response(self, *args):
        self.events.append("record_daily_response")
        return True

    def daily_response_counts(self, chat_id, prompt_date):
        self.events.append("daily_response_counts")
        return {"coffee": 1}

    def active_daily_callouts(self, chat_id):
        self.events.append("active_daily_callouts")
        return []


class _FakeContext:
    def __init__(self, db):
        self.application = type("Application", (), {"bot_data": {"db": db}})()


class DailyCallbackTests(unittest.TestCase):
    def test_callback_is_acknowledged_before_database_or_message_work(self):
        events = []
        query = _FakeQuery(events)
        update = type("Update", (), {"callback_query": query})()

        asyncio.run(bot.on_daily_answer(update, _FakeContext(_FakeDB(events))))

        self.assertEqual(events[0][0], "answer")
        self.assertEqual(events[1], "is_group_member")
        self.assertEqual(events[-1][0], "edit")


if __name__ == "__main__":
    unittest.main()
