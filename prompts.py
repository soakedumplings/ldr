"""The daily prompt bank + Gemini flavour.

Prompts fall into four buckets:

  * ACTIVITY   — tied to a member's LOCAL clock (lunch, wake-up, evening...).
                 The scheduler only fires these at a member whose local time
                 matches, and names that member with {name}.
  * SLEEP_PING — fired at the group of someone who's currently asleep; the
                 group leaves notes (sweet) or roasts them (savage).
  * GROUP      — everyone answers, no specific person, fires any time of day.
  * CONNECTION — softer "missing you" prompts; some name a {name}.

`flavour()` optionally runs the chosen line through Gemini so the exact wording
varies day to day. If Gemini is unavailable the original line is used verbatim.
"""
from __future__ import annotations

import random

# Activity prompts keyed by the local-time window they belong to.
# The scheduler maps a member's current local hour to one of these keys.
ACTIVITY_PROMPTS: dict[str, list[str]] = {
    "wake": [
        "Just-woke-up selfie, {name}. Raw. Ungoverned. Gremlin mode. 🛌",
        "Morning, {name}! Post your face before the coffee fixes it ☕😵",
        "{name} is waking up somewhere on Earth — first-thing-I-saw pic, GO 🌅",
    ],
    "lunch": [
        "{name}, it's noon where you are — lunch pic before you inhale it, coward 🍜",
        "Midday check: {name}, show us the sad desk lunch / gourmet flex 🍱",
        "It's lunchtime for {name}. Rate your meal AND your life, 1–10 🍕",
    ],
    "afternoon": [
        "It's mid-afternoon for {name} — show us the most cursed thing you can see right now 👀",
        "{name}, 3pm slump pic. Prove you're still conscious 🥱",
        "Coffee/tea run for {name}? Snap it and rate your will to live ☕",
    ],
    "evening": [
        "It's 5pm for {name} — show us your 'I'm done pretending to work' face 💼",
        "Golden hour where {name} is — one pretty pic of your view, make us jealous 🌇",
        "{name}, sunset check. Or ceiling check. We'll take anything 🌆",
    ],
    "night": [
        "Midnight snack cam, {name}. We know you're in the kitchen. Don't lie 🌃",
        "{name}, it's late for you — show us your winding-down setup 🛋️",
        "Nighttime for {name}: post the last thing you touched before bed 🌙",
    ],
}

# Fired at the GROUP of a sleeping member. Half sweet, half savage.
SLEEP_PINGS_SWEET = [
    "It's 3am for {name}. Say something nice they'll wake up to 🌙",
    "{name} is fast asleep. Leave them a note for the morning 💌",
    "Shhh — {name} is dreaming. Drop a memory of them you love 🫶",
    "{name} is offline in dreamland. Tell the group why you're glad they exist ✨",
]
SLEEP_PINGS_SAVAGE = [
    "It's 3am for {name}. They're unconscious and defenceless. Post your honest opinion 😈",
    "{name} is asleep. Leave a note. Bonus points if it's unhinged ✍️",
    "It's stupid-o'clock for {name}. Predict the dumb thing they'll do tomorrow 🔮",
    "{name} is dreaming right now. Guess what about — loser buys the next call 💭",
    "{name} can't defend themselves rn (asleep). Roast them lovingly 🔥",
]

# No specific target — everyone joins in. Fire any time.
GROUP_PROMPTS = [
    "EVERYONE: last photo in your camera roll. GO. No editing, no explaining 📸",
    "Show us your screen time number. No cropping. We're all disappointed together 📱",
    "Sum up your week so far in a movie title 🎬",
    "Ugliest selfie you can produce in 10 seconds. Beauty is banned today 🤪",
    "What's the weather where you are? Prove it with a window pic 🌦️",
    "Show us your current view without moving from where you're sitting 🪑",
    "Drop the song stuck in your head right now — we're building a group playlist 🎧",
]

# Softer connection prompts; {name} lines target a random member.
CONNECTION_PROMPTS_TARGETED = [
    "Send {name} a voice note — you haven't heard their voice in too long 🎙️",
]
CONNECTION_PROMPTS_GENERAL = [
    "Drop a throwback pic of the group. Instant nostalgia tax 📼",
]


def pick_activity(activity_key: str, name: str) -> str:
    lines = ACTIVITY_PROMPTS.get(activity_key)
    if not lines:
        return random.choice(GROUP_PROMPTS)
    return random.choice(lines).format(name=name)


def pick_sleep_ping(name: str) -> str:
    pool = SLEEP_PINGS_SWEET + SLEEP_PINGS_SAVAGE
    return random.choice(pool).format(name=name)


def pick_group_prompt() -> str:
    return random.choice(GROUP_PROMPTS)


def pick_connection_prompt(names: list[str]) -> str:
    """Prefer a targeted line if we have names to aim at; else a general one."""
    if names and random.random() < 0.6:
        return random.choice(CONNECTION_PROMPTS_TARGETED).format(
            name=random.choice(names)
        )
    return random.choice(CONNECTION_PROMPTS_GENERAL)


def flavour(gemini, base_line: str) -> str:
    """Optionally rephrase a prompt via Gemini in the bot's chaotic-funny voice.

    Falls back to the original line whenever Gemini is unavailable or the
    rewrite looks broken (too long / dropped the {name} intent).
    """
    if gemini is None or not getattr(gemini, "enabled", False):
        return base_line
    ask = (
        "Rewrite this friend-group prompt in a chaotic, funny, warm tone for a "
        "long-distance-friends Telegram bot. Keep it ONE short line, keep any "
        "names exactly as written, keep an emoji, and don't add quotes:\n\n"
        f"{base_line}"
    )
    out = gemini.generate(ask)
    if not out:
        return base_line
    out = out.strip().strip('"').split("\n")[0].strip()
    # Sanity guard: keep it short and don't let it drop a targeted name.
    if not out or len(out) > 200:
        return base_line
    return out
