# 🌍 LDR Bot

A Telegram bot for friends in a long-distance friendship across timezones. It
keeps you connected with lightweight daily check-ins and a weekly **Rose & Thorn**
photo ritual with streaks. No same-time coordination needed; everything is async.

- 🌹 **Weekly Rose & Thorn** — the bot DMs each person for **one photo + a caption**
  saying if it's a HIGH 🌹 or LOW 🥀 with a short note. Miss it → your streak dies
  publicly 💔. Sunday it posts a group recap (Gemini writes the intro).
- 📊 **Daily check-in** — one short question with predefined one-tap answers.
  Results appear as anonymous totals. Prompts rotate through the full bank before
  repeating. Anyone who misses two check-ins can receive a dramatic group callout.
- 🌍 **Multi-group aware** — add it to several friend groups. Recaps and
  daily check-ins go **only to the relevant group**, never leak across chats.
- ⚙️ **Per-person timezone + sleep window**, changeable anytime with `/setup`.

---

## Commands

| Command | What it does |
|---|---|
| `/setup <timezone> [sleep HH:MM-HH:MM]` | Set your timezone + optional sleep window. e.g. `/setup Asia/Singapore 01:00-08:00` |
| `/board` | Who's awake right now |
| `/me` | Your streak + settings |
| `/help` | Quick guide |

Default sleep window is **01:00–08:00**; everyone can set their own.

---

## What YOU need to do

### 1. Fill in the API keys (required)

```bash
cp .env.example .env
```

Open `.env` and replace the placeholders:

- **`TELEGRAM_BOT_TOKEN`** — required (see step 2).
- **`GEMINI_API_KEY`** — optional. Get a free key at
  https://aistudio.google.com/apikey . Standard keys start with `AIza...`.
  Without it the bot still works — only the optional recap introduction loses its
  AI-generated wording.

> The bot already has a **Gemini failover chain**: on a rate-limit (429) it
> tries `gemini-2.5-flash → 2.5-flash-lite → 2.0-flash → 2.0-flash-lite`, and if
> the whole chain is exhausted it backs off and retries. If everything still
> fails it quietly falls back to canned text — the bot never crashes over quota.

### 2. Create the Telegram bot (required)

1. In Telegram, message **@BotFather** → send `/newbot` → follow prompts.
2. Copy the token it gives you into `TELEGRAM_BOT_TOKEN` in `.env`.
3. **Disable Privacy Mode** so the bot can track group members:
   `/setprivacy` → pick your bot (`@your_bot_username`) → **Disable**.
4. Add the bot to your friend group(s). It'll greet everyone.
5. Everyone runs `/setup <timezone>` (in the group) so the bot knows their clock.

---

## Run it locally (to test)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Leave it running and it'll poll Telegram. Ctrl-C to stop. (You don't want to
keep your laptop on forever — see free hosting below.)

---

## 🆓 Free 24/7 hosting (no laptop babysitting)

The bot uses **long-polling** (outbound connections only), so there's no public
URL/server to expose. You just need a small always-on box + a persistent disk
for the SQLite streak file.

### Option A — Fly.io (easiest, recommended to start)

1. Install the CLI and sign in (free):
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth signup      # or: fly auth login
   ```
2. From this folder, launch (a `fly.toml` is already included — edit `app` name):
   ```bash
   fly launch --no-deploy
   ```
   When asked, say **no** to a public/HTTP service and **yes** to keeping the
   provided config.
3. Create the persistent volume (keeps streaks across restarts):
   ```bash
   fly volumes create ldr_data --size 1 --region sin
   ```
4. Set your secrets (do NOT commit them):
   ```bash
   fly secrets set TELEGRAM_BOT_TOKEN=123456:AA...   GEMINI_API_KEY=AIza...
   ```
5. Deploy:
   ```bash
   fly deploy --remote-only --depot=false
   ```
6. Check it's alive:
   ```bash
   fly logs
   ```

That's it — it runs 24/7. To update code later: `fly deploy` again.

> Fly's free allowance covers one tiny always-on machine like this. If they ever
> ask for a card it's just for verification; a 256MB shared VM stays within free
> limits.

---

## Privacy

The bot stores only what streaks and scheduling need: each person's timezone +
sleep window, group membership, streak counts, and one-tap daily check-in
responses. Daily response totals are shown anonymously. The current week's Rose
& Thorn entry keeps a Telegram photo reference + caption **only until the Sunday
recap posts**, then it's deleted. No chat messages are stored. Secrets live in
`.env` (git-ignored), never in code.

## Files

```
bot.py           commands, photo capture, group tracking, entrypoint
scheduler.py     hourly tick: daily prompts + weekly Rose & Thorn per group
prompts.py       short one-tap daily prompt bank and button rendering
gemini.py        Gemini model fallback chain + backoff (optional)
db.py            SQLite: members, groups, streaks, weekly submissions, daily responses
config.py        .env loader
.env.example     placeholder keys to copy to .env
Dockerfile       container for hosting
fly.toml         Fly.io deploy config
```
