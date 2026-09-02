"""Short, one-tap daily check-ins.

Every daily prompt has predefined options so nobody needs to write a reply.
The bank is intentionally direct and neutral. The scheduler rotates through
the bank before reusing a prompt.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class PromptOption:
    id: str
    label: str


@dataclass(frozen=True)
class DailyPrompt:
    id: str
    question: str
    options: tuple[PromptOption, ...]


def _prompt(prompt_id: str, question: str, *options: tuple[str, str]) -> DailyPrompt:
    return DailyPrompt(
        id=prompt_id,
        question=question,
        options=tuple(PromptOption(option_id, label) for option_id, label in options),
    )


DAILY_PROMPTS: tuple[DailyPrompt, ...] = (
    _prompt(
        "feeling_today",
        "How do you feel today?",
        ("good", "🙂 Good"),
        ("okay", "😐 Okay"),
        ("tired", "😴 Tired"),
        ("calm", "😌 Calm"),
        ("stressed", "😟 Stressed"),
        ("low", "😞 Low"),
        ("excited", "🤩 Excited"),
        ("numb", "😶 Numb"),
    ),
    _prompt(
        "mood_today",
        "What is your mood?",
        ("positive", "Positive"),
        ("neutral", "Neutral"),
        ("quiet", "Quiet"),
        ("busy", "Busy"),
        ("unsettled", "Unsettled"),
    ),
    _prompt(
        "coffee_or_tea",
        "Coffee or tea?",
        ("coffee", "☕ Coffee"),
        ("tea", "🍵 Tea"),
    ),
    _prompt(
        "early_or_late",
        "Early night or late night?",
        ("early", "Early night"),
        ("late", "Late night"),
    ),
    _prompt(
        "sweet_or_savoury",
        "Sweet or savoury?",
        ("sweet", "Sweet"),
        ("savoury", "Savoury"),
    ),
    _prompt(
        "stay_or_go",
        "Stay in or go out?",
        ("stay_in", "Stay in"),
        ("go_out", "Go out"),
    ),
    _prompt(
        "music_or_silence",
        "Music or silence?",
        ("music", "Music"),
        ("silence", "Silence"),
    ),
    _prompt(
        "rate_day",
        "Rate your day from 1–5.",
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ),
    _prompt(
        "rate_energy",
        "Rate your energy from 1–5.",
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ),
    _prompt(
        "rate_week",
        "Rate your week so far from 1–5.",
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ),
    _prompt(
        "rate_busy",
        "How busy are you today from 1–5?",
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ),
    _prompt(
        "describe_today",
        "One word for today.",
        ("good", "Good"),
        ("okay", "Okay"),
        ("busy", "Busy"),
        ("tiring", "Tiring"),
        ("difficult", "Difficult"),
        ("peaceful", "Peaceful"),
    ),
    _prompt(
        "describe_week",
        "One word for your week.",
        ("good", "Good"),
        ("busy", "Busy"),
        ("slow", "Slow"),
        ("difficult", "Difficult"),
        ("promising", "Promising"),
    ),
    _prompt(
        "doing_now",
        "What are you doing now?",
        ("work", "Working/studying"),
        ("resting", "Resting"),
        ("eating", "Eating"),
        ("commuting", "Commuting"),
        ("nothing", "Nothing much"),
    ),
    _prompt(
        "listening_now",
        "What are you listening to?",
        ("music", "Music"),
        ("podcast", "Podcast"),
        ("people", "People talking"),
        ("nothing", "Nothing"),
    ),
    _prompt(
        "ate_today",
        "What did you eat today?",
        ("home_cooked", "Home-cooked food"),
        ("takeaway", "Takeaway"),
        ("snacks", "Snacks"),
        ("restaurant", "Restaurant"),
        ("not_yet", "Not yet"),
    ),
    _prompt(
        "looking_forward_to",
        "What are you looking forward to?",
        ("rest", "Rest"),
        ("food", "Food"),
        ("weekend", "The weekend"),
        ("free_time", "Free time"),
        ("seeing_someone", "Seeing someone"),
        ("nothing", "Nothing specific"),
    ),
    _prompt(
        "went_well",
        "What went well today?",
        ("work", "Work/school"),
        ("food", "Food"),
        ("rest", "Rest"),
        ("people", "Friends/family"),
        ("small_win", "A small win"),
        ("nothing_yet", "Nothing yet"),
    ),
    _prompt(
        "difficult_today",
        "What was difficult today?",
        ("work", "Work/school"),
        ("time", "Time management"),
        ("people", "People"),
        ("energy", "Low energy"),
        ("nothing", "Nothing difficult"),
    ),
    _prompt(
        "made_easier",
        "What made today easier?",
        ("rest", "Rest"),
        ("food", "Food"),
        ("music", "Music"),
        ("routine", "Routine"),
        ("people", "People"),
        ("nothing", "Nothing yet"),
    ),
    _prompt(
        "improve_today",
        "What would improve today?",
        ("rest", "More rest"),
        ("food", "A good meal"),
        ("time", "More time"),
        ("company", "Company"),
        ("quiet", "Some quiet"),
        ("nothing", "Nothing"),
    ),
    _prompt(
        "need_more",
        "What do you need more of this week?",
        ("sleep", "Sleep"),
        ("rest", "Rest"),
        ("focus", "Focus"),
        ("fun", "Fun"),
        ("time", "Time"),
        ("support", "Support"),
    ),
)

_PROMPTS_BY_ID = {prompt.id: prompt for prompt in DAILY_PROMPTS}


def daily_prompt_ids() -> tuple[str, ...]:
    return tuple(prompt.id for prompt in DAILY_PROMPTS)


def get_daily_prompt(prompt_id: str) -> DailyPrompt:
    return _PROMPTS_BY_ID[prompt_id]


def choose_daily_prompt_id(used_ids: set[str]) -> str:
    available = [prompt.id for prompt in DAILY_PROMPTS if prompt.id not in used_ids]
    return random.choice(available or list(_PROMPTS_BY_ID))


def get_prompt_option(prompt_id: str, option_id: str) -> PromptOption | None:
    prompt = _PROMPTS_BY_ID.get(prompt_id)
    if prompt is None:
        return None
    return next((option for option in prompt.options if option.id == option_id), None)


def daily_keyboard(prompt: DailyPrompt, prompt_date: str):
    """Build a compact two-column inline keyboard for a daily prompt."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = [
        InlineKeyboardButton(
            option.label,
            callback_data=f"daily|{prompt_date}|{prompt.id}|{option.id}",
        )
        for option in prompt.options
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def format_daily_message(
    prompt: DailyPrompt,
    counts: dict[str, int],
    callouts=(),
) -> str:
    """Render the prompt, anonymous totals, and any dramatic callouts."""
    lines = [f"<b>{escape(prompt.question)}</b>", "", "<i>Anonymous totals</i>", ""]
    for option in prompt.options:
        lines.append(f"{escape(option.label)}: {counts.get(option.id, 0)}")

    if callouts:
        lines.extend(
            [
                "",
                "🚨 <b>Attendance emergency</b> 🚨",
                "",
                "We hope they are okay. We also hope they know we noticed.",
            ]
        )
        for member in callouts:
            mention = (
                f'<a href="tg://user?id={member.user_id}">'
                f"{escape(member.name)}</a>"
            )
            lines.append(
                f"{mention} has missed the last 2 check-ins. "
                "Their silence has been documented."
            )
    return "\n".join(lines)
