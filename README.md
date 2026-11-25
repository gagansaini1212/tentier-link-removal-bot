# Telegram Anti-Link Moderator Bot

Automatically detects and immediately deletes links posted (or edited) by non-admin users in Telegram groups.

## Features
- Detects `http://` / `https://` URLs, hidden `TEXT_LINK` hyperlinks, `t.me/` / `wa.me/` / shortener links, bare `domain.com` links, and links inside media captions.
- Also catches edited messages where a non-admin adds a link after posting.
- Exempts group owners, group administrators, anonymous admins, linked-channel auto-forwards, and optional `ADMIN_USER_IDS`.
- Requires **Group Admin** with **Delete Messages** permission.

## Setup & Run

1. Create a new bot via `@BotFather` and copy the token.
2. Disable Group Privacy in `@BotFather` (`/setprivacy` -> `Disable`) or make sure the bot is a Group Admin with **Delete Messages** enabled.
3. Create `.env`:
   ```bash
   cp .env.example .env
   ```
   Paste your `TELEGRAM_BOT_TOKEN` inside `.env`.
4. Start the bot:
   ```bash
   .venv/bin/python bot.py
   ```
