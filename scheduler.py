"""Scheduling logic: one daily check-in per group, plus weekly Rose & Thorn.

Everything is driven by a single hourly tick (`run_tick`) wired into
python-telegram-bot's JobQueue. Keeping it to one entry point means there is no
extra scheduler process to host — it rides along with the bot's long-polling
loop, which matters for free hosting.

Timezone rules that make the bot feel personal:
  * Daily check-ins are short, neutral, and answerable with one tap.
  * Every check-in is scoped to exactly one group and never crosses group chats.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from db import DB, Member
import prompts

log = logging.getLogger(__name__)

# Weekly cadence (UTC day-of-week: Mon=0 .. Sun=6).
_RT_OPEN_DOW = 4   # Friday: DM everyone for their submission
_RT_OPEN_HOUR = 10
_RT_RECAP_DOW = 6  # Sunday: post the recap + settle streaks
_RT_RECAP_HOUR = 18


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def _local_now(tz: str) -> datetime | None:
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return None


def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _is_asleep(member: Member, now: datetime) -> bool:
    """True if `now` (member-local) falls inside the member's sleep window.

    Handles windows that wrap past midnight (e.g. 23:00–07:00).
    """
    mins = _minutes_since_midnight(now)
    start, end = member.sleep_start, member.sleep_end
    if start <= end:
        return start <= mins < end
    return mins >= start or mins < end


def week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# --------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------
async def run_tick(bot, db: DB, gemini) -> None:
    """Called hourly. Handles daily check-ins + weekly Rose & Thorn per group."""
    now_utc = datetime.now(ZoneInfo("UTC"))
    wk = week_key(now_utc)

    for chat_id in db.all_group_ids():
        members = db.group_members(chat_id)
        if not members:
            continue
        state = db.get_group_state(chat_id)

        # --- weekly Rose & Thorn: open (Fri) ---
        if (
            now_utc.weekday() == _RT_OPEN_DOW
            and now_utc.hour >= _RT_OPEN_HOUR
            and state.get("last_rt_open") != wk
        ):
            await _open_rose_and_thorn(bot, db, chat_id, members, wk)
            db.set_group_state(chat_id, last_rt_open=wk)

        # --- weekly Rose & Thorn: recap (Sun) ---
        if (
            now_utc.weekday() == _RT_RECAP_DOW
            and now_utc.hour >= _RT_RECAP_HOUR
            and state.get("last_rt_recap") != wk
        ):
            await _recap_rose_and_thorn(bot, db, gemini, chat_id, members, wk)
            db.set_group_state(chat_id, last_rt_recap=wk)

        # --- daily prompt (once per UTC day per group) ---
        today = now_utc.date().isoformat()
        if state.get("last_daily_date") != today:
            await _send_daily_checkin(bot, db, chat_id, today)


async def _send_daily_checkin(bot, db: DB, chat_id: int, today: str) -> None:
    """Send a fresh one-tap check-in and record it only after delivery."""
    state = db.get_group_state(chat_id)
    cycle = int(state.get("daily_prompt_cycle") or 0)
    used_ids = db.used_daily_prompt_ids(chat_id, cycle)
    if len(used_ids) >= len(prompts.daily_prompt_ids()):
        cycle = db.next_daily_prompt_cycle(chat_id)
        used_ids = set()

    prompt_id = prompts.choose_daily_prompt_id(used_ids)
    prompt = prompts.get_daily_prompt(prompt_id)
    callouts = db.prepare_daily_callouts(chat_id, today)
    message = await bot.send_message(
        chat_id=chat_id,
        text=prompts.format_daily_message(prompt, {}, callouts),
        parse_mode="HTML",
        reply_markup=prompts.daily_keyboard(prompt, today),
    )
    db.record_daily_prompt(chat_id, today, prompt_id, cycle, message.message_id)
    db.set_group_state(chat_id, last_daily_date=today)


async def _open_rose_and_thorn(bot, db: DB, chat_id, members, wk: str) -> None:
    """DM every member of THIS group their weekly submission request."""
    for m in members:
        msg = (
            "🌹 *Rose & Thorn time!*\n\n"
            "Send me *one photo* from your week + a caption saying whether it's "
            "a *HIGH* 🌹 or a *LOW* 🥀, plus a quick line about it.\n\n"
            "Example caption: `high — finally passed my driving test 🚗`\n\n"
            "Miss it and your streak dies (publicly 💔). Just reply here with the pic!"
        )
        try:
            await bot.send_message(chat_id=m.user_id, text=msg, parse_mode="Markdown")
        except Exception as exc:
            # Can't DM someone who never /start-ed the bot in private — nudge in-group.
            log.info("Could not DM %s (%s): %s", m.name, m.user_id, exc)
            await _safe_send(
                bot,
                chat_id,
                f"🌹 {m.name}, I couldn't DM you for Rose & Thorn — "
                f"send me `/start` in private so I can reach you!",
            )


async def _recap_rose_and_thorn(bot, db: DB, gemini, chat_id, members, wk: str) -> None:
    """Post the group's recap, settle streaks, then wipe the week's pics."""
    subs = db.week_submissions(chat_id, wk)
    submitted_ids = {s.user_id for s in subs}

    # Header (Gemini adds flavour, with a canned fallback).
    header = _recap_header(gemini, len(subs), len(members))
    await _safe_send(bot, chat_id, header)

    # Each submission as a captioned photo.
    for s in subs:
        badge = "🌹 HIGH" if s.kind == "high" else "🥀 LOW"
        streak = db.bump_streak(chat_id, s.user_id)
        caption = f"{badge} — *{s.name}* (🔥 {streak}-week streak)\n{s.caption}"
        try:
            await bot.send_photo(
                chat_id=chat_id, photo=s.file_id, caption=caption, parse_mode="Markdown"
            )
        except Exception as exc:
            log.warning("Failed to post photo for %s: %s", s.name, exc)
            await _safe_send(bot, chat_id, caption)

    # The fallen: members who didn't submit lose their streak.
    fallen = []
    for m in members:
        if m.user_id not in submitted_ids:
            had = db.break_streak(chat_id, m.user_id)
            fallen.append((m.name, had))

    if fallen:
        lines = ["💔 *Streaks that died this week:*"]
        for name, had in fallen:
            if had > 0:
                lines.append(f"• {name} — {had}-week streak, gone. F 🪦")
            else:
                lines.append(f"• {name} — ghosted again. Presumed abducted 🛸")
        await _safe_send(bot, chat_id, "\n".join(lines))

    db.clear_week(chat_id, wk)


def _recap_header(gemini, n_subs: int, n_members: int) -> str:
    canned = (
        f"📰 *This week's Rose & Thorn recap!* {n_subs}/{n_members} of you "
        f"actually showed up. Here's how the week went 👇"
    )
    if gemini is None or not getattr(gemini, "enabled", False):
        return canned
    out = gemini.generate(
        "Write ONE short, funny, warm intro line (with an emoji) for a "
        "long-distance friend group's weekly 'Rose & Thorn' photo recap. "
        f"{n_subs} of {n_members} friends submitted. No quotes, one line."
    )
    return out.strip() if out else canned


async def _safe_send(bot, chat_id, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as exc:
        log.warning("send to %s failed (%s); retrying plain.", chat_id, exc)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as exc2:
            log.error("send to %s failed again: %s", chat_id, exc2)
