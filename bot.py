"""LDR bot — keeping long-distance friends attached, low effort, high chaos.

Commands: /start /help /setup /board /me
Weekly Rose & Thorn submissions arrive as a captioned photo in a private DM.
Daily prompts + weekly recaps are driven by an hourly JobQueue tick.

Run with long-polling (no public server needed) — see README for hosting.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import scheduler
import prompts
from config import load_config
from db import DB, DEFAULT_SLEEP_START, DEFAULT_SLEEP_END
from gemini import Gemini

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ldr")

_VALID_TZ = available_timezones()

HELP_TEXT = (
    "🌍 *LDR Bot* — keeping us attached, low effort, high chaos.\n\n"
    "*Commands*\n"
    "`/setup <timezone> [sleep HH:MM-HH:MM]` — tell me where you are\n"
    "   e.g. `/setup Asia/Singapore 01:00-08:00`\n"
    "   Default sleep window is *01:00–08:00*, but everyone can set their own.\n"
    "`/sleep HH:MM-HH:MM` — change *just* your sleep window anytime\n"
    "   e.g. `/sleep 23:30-07:30`\n"
    "`/board` — who's awake right now\n"
    "`/me` — your streak + settings\n"
    "`/help` — this\n\n"
    "*What I do on my own*\n"
    "🌹 *Weekly Rose & Thorn* — I DM you for *one* photo + a caption saying if "
    "it's a HIGH 🌹 or LOW 🥀 and a quick note. Miss it = streak dies (publicly 💔). "
    "Sunday I post the group recap.\n"
    "📊 *Daily check-in* — answer one short question with one tap. "
    "Results are shown as anonymous group totals.\n\n"
    "_Add me to your friend group, everyone runs /setup, then just live your "
    "life. I'll do the clingy part._"
)


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------
def _parse_sleep_window(text: str) -> tuple[int, int] | None:
    """Parse 'HH:MM-HH:MM' into (start_minutes, end_minutes)."""
    m = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", text.strip())
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if not (0 <= h1 < 24 and 0 <= h2 < 24 and 0 <= m1 < 60 and 0 <= m2 < 60):
        return None
    return (h1 * 60 + m1, h2 * 60 + m2)


def _fmt_minutes(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _display_name(user) -> str:
    return user.first_name or user.username or f"user{user.id}"


# --------------------------------------------------------------------------
# command handlers
# --------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey! I'm your long-distance-friends bot 🌍\n\n"
        "Starting me in private means I can DM you for weekly Rose & Thorn. "
        "Now run /setup so I know your timezone!\n",
    )
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.application.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/setup <timezone> [sleep HH:MM-HH:MM]`\n"
            "e.g. `/setup Asia/Singapore 01:00-08:00`\n\n"
            "Find your timezone name here: "
            "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
            parse_mode="Markdown",
        )
        return

    tz = args[0]
    if tz not in _VALID_TZ:
        await update.message.reply_text(
            f"Hmm, `{tz}` isn't a timezone I recognise. Use the 'TZ identifier' "
            f"form like `Asia/Singapore`, `Europe/London`, `America/New_York`.",
            parse_mode="Markdown",
        )
        return

    sleep_start, sleep_end = DEFAULT_SLEEP_START, DEFAULT_SLEEP_END
    if len(args) >= 2:
        parsed = _parse_sleep_window(" ".join(args[1:]))
        if parsed is None:
            await update.message.reply_text(
                "Couldn't read that sleep window. Format is `HH:MM-HH:MM`, "
                "e.g. `01:00-08:00`. (Timezone was saved though.)",
                parse_mode="Markdown",
            )
        else:
            sleep_start, sleep_end = parsed

    name = _display_name(user)
    db.upsert_member(user.id, name, tz, sleep_start, sleep_end)

    # In a group, this also enrols them in that group's rituals.
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        db.register_group(chat.id, chat.title)
        db.add_membership(chat.id, user.id)

    now = datetime.now(ZoneInfo(tz))
    await update.message.reply_text(
        f"✅ Got it, {name}!\n"
        f"🕐 Timezone: *{tz}* (your local time: {now:%H:%M})\n"
        f"😴 Sleep window: *{_fmt_minutes(sleep_start)}–{_fmt_minutes(sleep_end)}*\n\n"
        + (
            "You're enrolled in this group's Rose & Thorn 🌹\n"
            if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
            else "Tip: run /setup inside your friend group so I know who's in it!\n"
        )
        + "Change anytime by running /setup again, or just your sleep window "
        "with /sleep.",
        parse_mode="Markdown",
    )


async def cmd_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adjust just your sleep window, keeping your existing timezone."""
    db: DB = context.application.bot_data["db"]
    user = update.effective_user
    member = db.get_member(user.id)
    if not member:
        await update.message.reply_text(
            "Set your timezone first with `/setup <timezone>` 🌍",
            parse_mode="Markdown",
        )
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/sleep HH:MM-HH:MM`\n"
            "e.g. `/sleep 23:30-07:30`\n\n"
            f"Your current window is "
            f"*{_fmt_minutes(member.sleep_start)}–{_fmt_minutes(member.sleep_end)}*.",
            parse_mode="Markdown",
        )
        return

    parsed = _parse_sleep_window(" ".join(args))
    if parsed is None:
        await update.message.reply_text(
            "Couldn't read that. Format is `HH:MM-HH:MM`, e.g. `01:00-08:00` "
            "(overnight windows like `23:00-07:00` are fine too).",
            parse_mode="Markdown",
        )
        return

    sleep_start, sleep_end = parsed
    # Keep name/timezone, update only the window.
    db.upsert_member(user.id, member.name, member.timezone, sleep_start, sleep_end)
    await update.message.reply_text(
        f"😴 Updated your sleep window to "
        f"*{_fmt_minutes(sleep_start)}–{_fmt_minutes(sleep_end)}*.\n"
        "I won't fire wake-up prompts at you during it, and that's when others "
        "get the 'it's 3am for you' pings 🌙",
        parse_mode="Markdown",
    )


async def cmd_board(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.application.bot_data["db"]
    chat = update.effective_chat

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        members = db.group_members(chat.id)
    else:
        # In a DM, show all the groups this person shares with the bot.
        seen = {}
        for gid in db.groups_for_user(update.effective_user.id):
            for m in db.group_members(gid):
                seen[m.user_id] = m
        members = list(seen.values())

    if not members:
        await update.message.reply_text(
            "Nobody's set up yet! Everyone run `/setup <timezone>` first 🌍",
            parse_mode="Markdown",
        )
        return

    lines = ["🌍 *Who's around right now*\n"]
    for m in members:
        try:
            now = datetime.now(ZoneInfo(m.timezone))
        except Exception:
            continue
        asleep = scheduler._is_asleep(m, now)
        state = "🌙 asleep" if asleep else "☀️ awake"
        lines.append(f"• *{m.name}* — {now:%H:%M} {state}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.application.bot_data["db"]
    user = update.effective_user
    member = db.get_member(user.id)
    if not member:
        await update.message.reply_text(
            "You haven't set up yet! Run `/setup <timezone>` 🌍",
            parse_mode="Markdown",
        )
        return

    try:
        now_str = f"{datetime.now(ZoneInfo(member.timezone)):%H:%M}"
    except Exception:
        now_str = "??"

    lines = [
        f"👤 *{member.name}*",
        f"🕐 {member.timezone} (now {now_str})",
        f"😴 Sleep: {_fmt_minutes(member.sleep_start)}–{_fmt_minutes(member.sleep_end)}",
        "",
        "*Rose & Thorn streaks*",
    ]
    groups = db.groups_for_user(user.id)
    if not groups:
        lines.append("_Not in any group yet — run /setup inside your friend group._")
    else:
        for gid in groups:
            cur, best = db.get_streak(gid, user.id)
            lines.append(f"• 🔥 {cur}-week streak (best: {best})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --------------------------------------------------------------------------
# daily one-tap check-ins
# --------------------------------------------------------------------------
async def on_daily_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record one valid daily answer and refresh anonymous totals."""
    query = update.callback_query
    # A callback must be acknowledged immediately or Telegram keeps the button
    # spinner running while the database and message update are in progress.
    await query.answer()

    parts = (query.data or "").split("|", 3)
    if len(parts) != 4 or parts[0] != "daily":
        return

    _, prompt_date, prompt_id, option_id = parts
    chat = query.message.chat
    user = query.from_user
    db: DB = context.application.bot_data["db"]
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if not db.is_group_member(chat.id, user.id):
        return

    daily_prompt = db.get_daily_prompt(chat.id, prompt_date)
    option = prompts.get_prompt_option(prompt_id, option_id)
    if (
        daily_prompt is None
        or db.get_group_state(chat.id).get("last_daily_date") != prompt_date
        or daily_prompt["prompt_id"] != prompt_id
        or option is None
    ):
        return

    inserted = db.record_daily_response(
        chat.id, user.id, prompt_date, prompt_id, option_id
    )
    if not inserted:
        return

    counts = db.daily_response_counts(chat.id, prompt_date)
    prompt = prompts.get_daily_prompt(prompt_id)
    await query.edit_message_text(
        text=prompts.format_daily_message(
            prompt, counts, db.active_daily_callouts(chat.id)
        ),
        parse_mode="HTML",
        reply_markup=prompts.daily_keyboard(prompt, prompt_date),
    )


# --------------------------------------------------------------------------
# Rose & Thorn photo capture (private DM only)
# --------------------------------------------------------------------------
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A captioned photo in a private chat = a Rose & Thorn submission."""
    chat = update.effective_chat
    if chat.type != ChatType.PRIVATE:
        return  # only DMs are submissions; ignore group photos

    db: DB = context.application.bot_data["db"]
    user = update.effective_user
    member = db.get_member(user.id)
    if not member:
        await update.message.reply_text(
            "Cute pic! But run `/setup <timezone>` first so I know who you are 🌍",
            parse_mode="Markdown",
        )
        return

    groups = db.groups_for_user(user.id)
    if not groups:
        await update.message.reply_text(
            "I don't know which friend group this is for yet — run /setup inside "
            "your group chat, then resend the pic 🌹",
        )
        return

    caption = (update.message.caption or "").strip()
    kind = _detect_kind(caption)
    if kind is None:
        await update.message.reply_text(
            "Almost! Add a caption saying if it's a *HIGH* 🌹 or *LOW* 🥀 plus a "
            "quick note.\nExample: `high — finally passed my driving test 🚗`",
            parse_mode="Markdown",
        )
        return

    file_id = update.message.photo[-1].file_id  # highest resolution
    wk = scheduler.week_key(datetime.now(ZoneInfo("UTC")))
    for gid in groups:
        db.save_submission(gid, user.id, wk, kind, caption, file_id)

    badge = "🌹 HIGH" if kind == "high" else "🥀 LOW"
    await update.message.reply_text(
        f"Locked in your {badge} for this week — streak safe 🔒🔥\n"
        "It'll show up in the group recap on Sunday. Thanks for showing up 💛"
    )


def _detect_kind(caption: str) -> str | None:
    low = caption.lower()
    if re.search(r"\bhigh\b|🌹|rose", low):
        return "high"
    if re.search(r"\blow\b|🥀|thorn", low):
        return "low"
    return None


# --------------------------------------------------------------------------
# group membership tracking
# --------------------------------------------------------------------------
async def on_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register a group and enrol known members as they chat.

    We only enrol people who've already done /setup (so we have their tz);
    others are gently nudged once via /setup in the group.
    """
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    db: DB = context.application.bot_data["db"]
    db.register_group(chat.id, chat.title)

    user = update.effective_user
    if user and db.get_member(user.id):
        db.add_membership(chat.id, user.id)


async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the group when the bot is added."""
    chat = update.effective_chat
    db: DB = context.application.bot_data["db"]
    me = await context.bot.get_me()
    for member in update.message.new_chat_members or []:
        if member.id == me.id:
            db.register_group(chat.id, chat.title)
            await update.message.reply_text(
                "Hey friends! 🌍 I'm here to keep you attached across timezones "
                "with zero effort.\n\n"
                "👉 *Everyone run* `/setup <timezone>` (e.g. "
                "`/setup Asia/Singapore`) so I know your clock.\n"
                "Then /help to see the chaos I'll bring 😈",
                parse_mode="Markdown",
            )
            return


# --------------------------------------------------------------------------
# the hourly job
# --------------------------------------------------------------------------
async def _tick_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.application.bot_data["db"]
    gemini: Gemini = context.application.bot_data["gemini"]
    try:
        await scheduler.run_tick(context.bot, db, gemini)
    except Exception as exc:  # never let the scheduler kill the bot
        log.exception("tick failed: %s", exc)


# --------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------
def main() -> None:
    cfg = load_config()
    cfg.require_telegram()

    db = DB(cfg.db_path)
    gemini = Gemini(cfg.gemini_api_key)
    if not cfg.has_gemini:
        log.warning("Running WITHOUT Gemini — using pre-written prompts/recaps.")

    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data["db"] = db
    app.bot_data["gemini"] = gemini

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("board", cmd_board))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CallbackQueryHandler(on_daily_answer, pattern=r"^daily\|"))

    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group
        )
    )
    # Passive membership tracking: any non-command group text.
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            on_group_activity,
        )
    )

    # Hourly tick drives daily prompts + weekly Rose & Thorn.
    app.job_queue.run_repeating(_tick_job, interval=3600, first=15)

    log.info("LDR bot starting (long-polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
