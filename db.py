"""SQLite persistence for the LDR bot.

We store only what streaks and scheduling need:
  * members  — a person's timezone + personal sleep window (global to the person)
  * groups   — group chats the bot lives in
  * memberships — which people belong to which group, plus their per-group streak
  * submissions — the current open week's Rose & Thorn entries (cleared after recap)
  * daily_prompts/responses — one-tap daily check-ins and anonymous totals
  * daily explanation polls/votes — end-of-day explanation selection
  * group_state — bookkeeping so each group gets one daily prompt per day

We never store chat messages or the pictures themselves — only a Telegram
file_id reference for the current week, which is discarded once the recap posts.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

# Default sleep window: 01:00–08:00 local. Stored as minutes since midnight.
DEFAULT_SLEEP_START = 1 * 60
DEFAULT_SLEEP_END = 8 * 60


@dataclass
class Member:
    user_id: int
    name: str
    timezone: str
    sleep_start: int  # minutes since local midnight
    sleep_end: int


@dataclass
class Submission:
    user_id: int
    name: str
    kind: str  # "high" or "low"
    caption: str
    file_id: str


@dataclass
class DailyRespondent:
    user_id: int
    name: str
    option_id: str


@dataclass
class DailyExplanationWinner:
    user_id: int
    name: str
    option_id: str
    vote_count: int


class DB:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS members (
                    user_id     INTEGER PRIMARY KEY,
                    name        TEXT NOT NULL,
                    timezone    TEXT NOT NULL,
                    sleep_start INTEGER NOT NULL,
                    sleep_end   INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    title   TEXT
                );

                CREATE TABLE IF NOT EXISTS memberships (
                    chat_id        INTEGER NOT NULL,
                    user_id        INTEGER NOT NULL,
                    current_streak INTEGER NOT NULL DEFAULT 0,
                    best_streak    INTEGER NOT NULL DEFAULT 0,
                    daily_callout_active INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS submissions (
                    chat_id  INTEGER NOT NULL,
                    user_id  INTEGER NOT NULL,
                    week_key TEXT NOT NULL,
                    kind     TEXT NOT NULL,
                    caption  TEXT NOT NULL,
                    file_id  TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id, week_key)
                );

                CREATE TABLE IF NOT EXISTS group_state (
                    chat_id         INTEGER PRIMARY KEY,
                    last_daily_date TEXT,
                    last_daily_summary_date TEXT,
                    last_rt_open    TEXT,
                    last_rt_recap   TEXT,
                    daily_prompt_cycle INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS daily_prompts (
                    chat_id     INTEGER NOT NULL,
                    prompt_date TEXT NOT NULL,
                    prompt_id   TEXT NOT NULL,
                    cycle       INTEGER NOT NULL DEFAULT 0,
                    message_id  INTEGER,
                    PRIMARY KEY (chat_id, prompt_date)
                );

                CREATE TABLE IF NOT EXISTS daily_responses (
                    chat_id     INTEGER NOT NULL,
                    prompt_date TEXT NOT NULL,
                    user_id     INTEGER NOT NULL,
                    prompt_id   TEXT NOT NULL,
                    option_id   TEXT NOT NULL,
                    PRIMARY KEY (chat_id, prompt_date, user_id)
                );

                CREATE TABLE IF NOT EXISTS daily_explanation_polls (
                    chat_id          INTEGER NOT NULL,
                    prompt_date      TEXT NOT NULL,
                    summary_message_id INTEGER,
                    message_id       INTEGER,
                    closes_at        TEXT NOT NULL,
                    closed_at        TEXT,
                    winner_user_id INTEGER,
                    announcement_sent_at TEXT,
                    PRIMARY KEY (chat_id, prompt_date)
                );

                CREATE TABLE IF NOT EXISTS daily_explanation_votes (
                    chat_id       INTEGER NOT NULL,
                    prompt_date   TEXT NOT NULL,
                    voter_id      INTEGER NOT NULL,
                    target_user_id INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, prompt_date, voter_id)
                );
                """
            )
            self._ensure_column(cur, "memberships", "daily_callout_active", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(cur, "group_state", "daily_prompt_cycle", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(cur, "group_state", "last_daily_summary_date", "TEXT")
            self._ensure_column(cur, "daily_explanation_polls", "summary_message_id", "INTEGER")
            self._ensure_column(cur, "daily_explanation_polls", "announcement_sent_at", "TEXT")

    @staticmethod
    def _ensure_column(cur, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    # ---- members -------------------------------------------------------
    def upsert_member(
        self,
        user_id: int,
        name: str,
        timezone: str,
        sleep_start: int = DEFAULT_SLEEP_START,
        sleep_end: int = DEFAULT_SLEEP_END,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO members (user_id, name, timezone, sleep_start, sleep_end)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name=excluded.name,
                    timezone=excluded.timezone,
                    sleep_start=excluded.sleep_start,
                    sleep_end=excluded.sleep_end
                """,
                (user_id, name, timezone, sleep_start, sleep_end),
            )

    def get_member(self, user_id: int) -> Member | None:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM members WHERE user_id=?", (user_id,)
            ).fetchone()
        return _row_to_member(row) if row else None

    # ---- groups & membership ------------------------------------------
    def register_group(self, chat_id: int, title: str | None) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO groups (chat_id, title) VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title
                """,
                (chat_id, title),
            )

    def add_membership(self, chat_id: int, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO memberships (chat_id, user_id)
                VALUES (?, ?)
                """,
                (chat_id, user_id),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def all_group_ids(self) -> list[int]:
        with self._cursor() as cur:
            rows = cur.execute("SELECT chat_id FROM groups").fetchall()
        return [r["chat_id"] for r in rows]

    def group_members(self, chat_id: int) -> list[Member]:
        """Members of a group who have completed /setup (have a timezone)."""
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT m.* FROM members m
                JOIN memberships ms ON ms.user_id = m.user_id
                WHERE ms.chat_id = ?
                ORDER BY m.name COLLATE NOCASE
                """,
                (chat_id,),
            ).fetchall()
        return [_row_to_member(r) for r in rows]

    def groups_for_user(self, user_id: int) -> list[int]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT chat_id FROM memberships WHERE user_id=?", (user_id,)
            ).fetchall()
        return [r["chat_id"] for r in rows]

    def is_group_member(self, chat_id: int, user_id: int) -> bool:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT 1 FROM memberships WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return row is not None

    # ---- submissions ---------------------------------------------------
    def save_submission(
        self,
        chat_id: int,
        user_id: int,
        week_key: str,
        kind: str,
        caption: str,
        file_id: str,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO submissions (chat_id, user_id, week_key, kind, caption, file_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id, week_key) DO UPDATE SET
                    kind=excluded.kind,
                    caption=excluded.caption,
                    file_id=excluded.file_id
                """,
                (chat_id, user_id, week_key, kind, caption, file_id),
            )

    def has_submitted(self, chat_id: int, user_id: int, week_key: str) -> bool:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT 1 FROM submissions WHERE chat_id=? AND user_id=? AND week_key=?",
                (chat_id, user_id, week_key),
            ).fetchone()
        return row is not None

    def week_submissions(self, chat_id: int, week_key: str) -> list[Submission]:
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT s.user_id, m.name, s.kind, s.caption, s.file_id
                FROM submissions s
                JOIN members m ON m.user_id = s.user_id
                WHERE s.chat_id=? AND s.week_key=?
                ORDER BY m.name COLLATE NOCASE
                """,
                (chat_id, week_key),
            ).fetchall()
        return [
            Submission(r["user_id"], r["name"], r["kind"], r["caption"], r["file_id"])
            for r in rows
        ]

    def clear_week(self, chat_id: int, week_key: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM submissions WHERE chat_id=? AND week_key=?",
                (chat_id, week_key),
            )

    # ---- streaks -------------------------------------------------------
    def get_streak(self, chat_id: int, user_id: int) -> tuple[int, int]:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT current_streak, best_streak FROM memberships WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        if not row:
            return (0, 0)
        return (row["current_streak"], row["best_streak"])

    def bump_streak(self, chat_id: int, user_id: int) -> int:
        """Increment a member's streak; keep best_streak as the high-water mark."""
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE memberships
                SET current_streak = current_streak + 1,
                    best_streak = MAX(best_streak, current_streak + 1)
                WHERE chat_id=? AND user_id=?
                """,
                (chat_id, user_id),
            )
            row = cur.execute(
                "SELECT current_streak FROM memberships WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return row["current_streak"] if row else 0

    def break_streak(self, chat_id: int, user_id: int) -> int:
        """Reset streak to 0, returning the streak length that just died."""
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT current_streak FROM memberships WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            had = row["current_streak"] if row else 0
            cur.execute(
                "UPDATE memberships SET current_streak = 0 WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
        return had

    # ---- group scheduling state ---------------------------------------
    def get_group_state(self, chat_id: int) -> dict:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM group_state WHERE chat_id=?", (chat_id,)
            ).fetchone()
        if not row:
            return {
                "last_daily_date": None,
                "last_daily_summary_date": None,
                "last_rt_open": None,
                "last_rt_recap": None,
                "daily_prompt_cycle": 0,
            }
        return dict(row)

    def set_group_state(self, chat_id: int, **fields) -> None:
        if not fields:
            return
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO group_state (chat_id) VALUES (?)", (chat_id,)
            )
            assignments = ", ".join(f"{k}=?" for k in fields)
            cur.execute(
                f"UPDATE group_state SET {assignments} WHERE chat_id=?",
                (*fields.values(), chat_id),
            )

    # ---- one-tap daily check-ins --------------------------------------
    def daily_prompt_cycle(self, chat_id: int) -> int:
        return int(self.get_group_state(chat_id).get("daily_prompt_cycle") or 0)

    def used_daily_prompt_ids(self, chat_id: int, cycle: int) -> set[str]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT DISTINCT prompt_id FROM daily_prompts WHERE chat_id=? AND cycle=?",
                (chat_id, cycle),
            ).fetchall()
        return {row["prompt_id"] for row in rows}

    def next_daily_prompt_cycle(self, chat_id: int) -> int:
        cycle = self.daily_prompt_cycle(chat_id) + 1
        self.set_group_state(chat_id, daily_prompt_cycle=cycle)
        return cycle

    def record_daily_prompt(
        self,
        chat_id: int,
        prompt_date: str,
        prompt_id: str,
        cycle: int = 0,
        message_id: int | None = None,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_prompts
                    (chat_id, prompt_date, prompt_id, cycle, message_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, prompt_date) DO UPDATE SET
                    prompt_id=excluded.prompt_id,
                    cycle=excluded.cycle,
                    message_id=excluded.message_id
                """,
                (chat_id, prompt_date, prompt_id, cycle, message_id),
            )

    def update_daily_prompt_message(self, chat_id: int, prompt_date: str, message_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE daily_prompts SET message_id=? WHERE chat_id=? AND prompt_date=?",
                (message_id, chat_id, prompt_date),
            )

    def get_daily_prompt(self, chat_id: int, prompt_date: str) -> dict | None:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM daily_prompts WHERE chat_id=? AND prompt_date=?",
                (chat_id, prompt_date),
            ).fetchone()
        return dict(row) if row else None

    def record_daily_response(
        self,
        chat_id: int,
        user_id: int,
        prompt_date: str,
        prompt_id: str,
        option_id: str,
    ) -> bool:
        with self._cursor() as cur:
            existing = cur.execute(
                """
                SELECT option_id
                FROM daily_responses
                WHERE chat_id=? AND prompt_date=? AND user_id=?
                """,
                (chat_id, prompt_date, user_id),
            ).fetchone()
            if existing and existing["option_id"] == option_id:
                return False

            cur.execute(
                """
                INSERT INTO daily_responses
                    (chat_id, prompt_date, user_id, prompt_id, option_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, prompt_date, user_id) DO UPDATE SET
                    prompt_id=excluded.prompt_id,
                    option_id=excluded.option_id
                """,
                (chat_id, prompt_date, user_id, prompt_id, option_id),
            )
            cur.execute(
                """
                UPDATE memberships
                SET daily_callout_active=0
                WHERE chat_id=? AND user_id=?
                """,
                (chat_id, user_id),
            )
        return True

    def daily_response_counts(self, chat_id: int, prompt_date: str) -> dict[str, int]:
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT option_id, COUNT(*) AS total
                FROM daily_responses
                WHERE chat_id=? AND prompt_date=?
                GROUP BY option_id
                """,
                (chat_id, prompt_date),
            ).fetchall()
        return {row["option_id"]: row["total"] for row in rows}

    def prepare_daily_callouts(self, chat_id: int, before_date: str) -> list[Member]:
        """Mark and return members who missed the previous two prompts once."""
        with self._cursor() as cur:
            prompt_rows = cur.execute(
                """
                SELECT prompt_date
                FROM daily_prompts
                WHERE chat_id=? AND prompt_date < ?
                ORDER BY prompt_date DESC
                LIMIT 2
                """,
                (chat_id, before_date),
            ).fetchall()
            prompt_dates = [row["prompt_date"] for row in prompt_rows]
            if len(prompt_dates) < 2:
                return []

            rows = cur.execute(
                """
                SELECT m.*
                FROM members m
                JOIN memberships ms ON ms.user_id=m.user_id
                WHERE ms.chat_id=? AND ms.daily_callout_active=0
                ORDER BY m.name COLLATE NOCASE
                """,
                (chat_id,),
            ).fetchall()

            callouts = []
            for row in rows:
                answered = cur.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM daily_responses
                    WHERE chat_id=? AND user_id=? AND prompt_date IN (?, ?)
                    """,
                    (chat_id, row["user_id"], prompt_dates[0], prompt_dates[1]),
                ).fetchone()["total"]
                if answered == 0:
                    cur.execute(
                        """
                        UPDATE memberships
                        SET daily_callout_active=1
                        WHERE chat_id=? AND user_id=?
                        """,
                        (chat_id, row["user_id"]),
                    )
                    callouts.append(_row_to_member(row))
        return callouts

    def active_daily_callouts(self, chat_id: int) -> list[Member]:
        """Return members currently marked for a missed-check-in callout."""
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT m.*
                FROM members m
                JOIN memberships ms ON ms.user_id=m.user_id
                WHERE ms.chat_id=? AND ms.daily_callout_active=1
                ORDER BY m.name COLLATE NOCASE
                """,
                (chat_id,),
            ).fetchall()
        return [_row_to_member(row) for row in rows]

    # ---- end-of-day explanation polls -------------------------------
    def daily_respondents(self, chat_id: int, prompt_date: str) -> list[DailyRespondent]:
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT r.user_id, m.name, r.option_id
                FROM daily_responses r
                JOIN members m ON m.user_id=r.user_id
                JOIN memberships ms ON ms.chat_id=r.chat_id AND ms.user_id=r.user_id
                WHERE r.chat_id=? AND r.prompt_date=?
                ORDER BY m.name COLLATE NOCASE
                """,
                (chat_id, prompt_date),
            ).fetchall()
        return [DailyRespondent(row["user_id"], row["name"], row["option_id"]) for row in rows]

    def record_daily_explanation_poll(
        self,
        chat_id: int,
        prompt_date: str,
        summary_message_id: int,
        message_id: int,
        closes_at: str,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_explanation_polls
                    (chat_id, prompt_date, summary_message_id, message_id, closes_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, prompt_date) DO UPDATE SET
                    summary_message_id=excluded.summary_message_id,
                    message_id=excluded.message_id,
                    closes_at=excluded.closes_at
                """,
                (chat_id, prompt_date, summary_message_id, message_id, closes_at),
            )

    def get_daily_explanation_poll(self, chat_id: int, prompt_date: str) -> dict | None:
        with self._cursor() as cur:
            row = cur.execute(
                """
                SELECT * FROM daily_explanation_polls
                WHERE chat_id=? AND prompt_date=?
                """,
                (chat_id, prompt_date),
            ).fetchone()
        return dict(row) if row else None

    def due_daily_explanation_polls(self, chat_id: int, now_iso: str) -> list[dict]:
        now = _parse_iso(now_iso)
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT * FROM daily_explanation_polls
                WHERE chat_id=? AND (closed_at IS NULL OR announcement_sent_at IS NULL)
                ORDER BY closes_at
                """,
                (chat_id,),
            ).fetchall()
        return [
            dict(row)
            for row in rows
            if row["announcement_sent_at"] is None
            and (
                row["closed_at"] is not None
                or _parse_iso(row["closes_at"]) <= now
            )
        ]

    def mark_daily_explanation_announced(
        self, chat_id: int, prompt_date: str, sent_at: str
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE daily_explanation_polls
                SET announcement_sent_at=?
                WHERE chat_id=? AND prompt_date=?
                """,
                (sent_at, chat_id, prompt_date),
            )

    def record_explanation_vote(
        self,
        chat_id: int,
        prompt_date: str,
        voter_id: int,
        target_user_id: int,
        now_iso: str | None = None,
    ) -> bool:
        with self._cursor() as cur:
            poll = cur.execute(
                """
                SELECT closed_at, closes_at FROM daily_explanation_polls
                WHERE chat_id=? AND prompt_date=?
                """,
                (chat_id, prompt_date),
            ).fetchone()
            target = cur.execute(
                """
                SELECT 1 FROM daily_responses
                WHERE chat_id=? AND prompt_date=? AND user_id=?
                """,
                (chat_id, prompt_date, target_user_id),
            ).fetchone()
            if not poll or poll["closed_at"] is not None or not target:
                return False
            if now_iso is not None and _parse_iso(now_iso) >= _parse_iso(poll["closes_at"]):
                return False

            existing = cur.execute(
                """
                SELECT target_user_id FROM daily_explanation_votes
                WHERE chat_id=? AND prompt_date=? AND voter_id=?
                """,
                (chat_id, prompt_date, voter_id),
            ).fetchone()
            if existing and existing["target_user_id"] == target_user_id:
                return False

            cur.execute(
                """
                INSERT INTO daily_explanation_votes
                    (chat_id, prompt_date, voter_id, target_user_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, prompt_date, voter_id) DO UPDATE SET
                    target_user_id=excluded.target_user_id
                """,
                (chat_id, prompt_date, voter_id, target_user_id),
            )
        return True

    def explanation_vote_counts(self, chat_id: int, prompt_date: str) -> dict[int, int]:
        with self._cursor() as cur:
            rows = cur.execute(
                """
                SELECT target_user_id, COUNT(*) AS total
                FROM daily_explanation_votes
                WHERE chat_id=? AND prompt_date=?
                GROUP BY target_user_id
                """,
                (chat_id, prompt_date),
            ).fetchall()
        return {row["target_user_id"]: row["total"] for row in rows}

    def close_daily_explanation_poll(
        self, chat_id: int, prompt_date: str, now_iso: str
    ) -> DailyExplanationWinner | None:
        with self._cursor() as cur:
            poll = cur.execute(
                """
                SELECT * FROM daily_explanation_polls
                WHERE chat_id=? AND prompt_date=?
                """,
                (chat_id, prompt_date),
            ).fetchone()
            if not poll or _parse_iso(now_iso) < _parse_iso(poll["closes_at"]):
                return None

            if poll["closed_at"] is not None:
                if poll["winner_user_id"] is None:
                    return None
                row = cur.execute(
                    """
                    SELECT m.user_id, m.name, r.option_id,
                           COUNT(v.voter_id) AS vote_count
                    FROM members m
                    JOIN daily_responses r
                      ON r.chat_id=? AND r.prompt_date=? AND r.user_id=m.user_id
                    JOIN daily_explanation_votes v
                      ON v.chat_id=? AND v.prompt_date=? AND v.target_user_id=m.user_id
                    WHERE m.user_id=?
                    GROUP BY m.user_id, m.name, r.option_id
                    """,
                    (chat_id, prompt_date, chat_id, prompt_date, poll["winner_user_id"]),
                ).fetchone()
                return _row_to_explanation_winner(row) if row else None

            row = cur.execute(
                """
                SELECT m.user_id, m.name, r.option_id,
                       COUNT(v.voter_id) AS vote_count
                FROM daily_explanation_votes v
                JOIN members m ON m.user_id=v.target_user_id
                JOIN daily_responses r
                  ON r.chat_id=v.chat_id AND r.prompt_date=v.prompt_date
                 AND r.user_id=v.target_user_id
                WHERE v.chat_id=? AND v.prompt_date=?
                GROUP BY m.user_id, m.name, r.option_id
                ORDER BY vote_count DESC, m.name COLLATE NOCASE
                LIMIT 1
                """,
                (chat_id, prompt_date),
            ).fetchone()
            winner_id = row["user_id"] if row else None
            cur.execute(
                """
                UPDATE daily_explanation_polls
                SET closed_at=?, winner_user_id=?
                WHERE chat_id=? AND prompt_date=?
                """,
                (now_iso, winner_id, chat_id, prompt_date),
            )
            return _row_to_explanation_winner(row) if row else None


def _row_to_member(row: sqlite3.Row) -> Member:
    return Member(
        user_id=row["user_id"],
        name=row["name"],
        timezone=row["timezone"],
        sleep_start=row["sleep_start"],
        sleep_end=row["sleep_end"],
    )


def _row_to_explanation_winner(row: sqlite3.Row) -> DailyExplanationWinner:
    return DailyExplanationWinner(
        user_id=row["user_id"],
        name=row["name"],
        option_id=row["option_id"],
        vote_count=row["vote_count"],
    )


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
