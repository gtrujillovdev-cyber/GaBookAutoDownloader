# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Commands

```bash
# Run all tests (must pass 100% before any commit)
python -m unittest discover -s tests

# Run a single test class
python -m unittest tests.test_features.TestHardening

# Run a single test method
python -m unittest tests.test_features.TestHardening.test_stream_rejects_html_error_page

# Start the bot locally (requires .env)
python main.py

# Install dependencies
pip install -r requirements.txt

# Pre-commit cleanup
find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -prune -exec rm -rf {} + \
  && find . -name ".DS_Store" -delete && find . -name "*.log" -delete
```

## Architecture

The project is a Telegram bot (python-telegram-bot v20+, async) structured in three layers:

```
main.py / bot.py (wrapper)
    └── src/gabook/bot.py          # All Telegram handlers + UX logic
            ├── src/gabook/config.py           # Single source of truth for env vars, constants, paths
            └── src/gabook/services/
                    ├── book_client.py         # Multi-source EPUB search + download
                    ├── kindle_mailer.py       # Email delivery via Mailjet REST API
                    ├── gmail_monitor.py       # IMAP polling for Amazon delivery confirmation
                    ├── user_manager.py        # User persistence (Upstash Redis or JSON)
                    └── health_server.py       # HTTP /health endpoint for Render keep-alive
```

### Key data flows

**Search and deliver a book:**
1. User types title → `text_message_handler` → `handle_search` (bot.py)
2. `search_epubs` (book_client.py) fans out to 8 sources in parallel (Libgen, Archive.org, OpenLibrary, Gutenberg, Standard Ebooks, ManyBooks, Anna's Archive, Z-Library)
3. Results cached in `SEARCH_SESSIONS` dict (TTL 2h, max 150); paginated 5 per page via `build_search_page_markup`
4. User selects a book → `execute_book_send` → `download_epub` (streams to `downloads/` with UUID suffix)
5. `send_to_kindle` (Mailjet REST, port 443) or sends to personal email
6. `monitor_kindle_delivery` (IMAP) polls for Amazon confirmation email and auto-clicks the verification link

**User storage:** `user_manager.py` routes all reads/writes through a single Redis key (`gabook:users`) when `UPSTASH_REDIS_REST_URL` is set; falls back to `users.json` locally. All writes are protected by `threading.Lock` via the `@_locked` decorator.

### Critical invariants

- **`escape_md(text)`** must wrap every dynamic string before it reaches `reply_text(..., parse_mode=ParseMode.MARKDOWN)` — missing it crashes message delivery with `Can't parse entities`.
- **`send_to_kindle`** uses Mailjet REST API (not SMTP). Render free tier blocks outbound SMTP ports; Mailjet bypasses this via HTTPS. File cap is 10 MB raw (Mailjet limit) / 22 MB (Gmail guard).
- **`monitor_kindle_delivery`** opens one IMAP connection per call, uses `mail.noop()` for keepalive, and always closes in `finally`. Never call it inside a polling loop.
- **`access_guard`** is registered as `group=-1` handler, runs before everything else. When `ALLOWED_USER_IDS` is non-empty, it raises `ApplicationHandlerStop` for unknown users.
- **`SEARCH_SESSIONS`** lives in RAM. `cleanup_expired_sessions()` must be called periodically to prevent memory leaks in 24/7 operation.
- **`download_epub`** falls back: direct URL → Archive.org metadata API → Libgen mirrors. The `progress_cb` must be forwarded to all branches (tested in `test_download_epub_propagates_progress_cb_to_all_sources`).

### Deployment

- **Production:** Render.com Web Service, auto-deploys on push to `main`.
- **Keep-alive:** UptimeRobot pings `/health` every 5 min; `health_server.py` serves it on `$PORT` in a daemon thread.
- **No local daemon:** The macOS launchd agent has been permanently removed. Running a second bot instance causes `telegram.error.Conflict 409`.
- **Verify after deploy:** `curl https://gabookautodownloader.onrender.com/health`

### Environment variables

All secrets live in `.env` locally and in Render's dashboard in production. See `.env.example` for the full list. Key ones: `TELEGRAM_BOT_TOKEN`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MAILJET_API_KEY`, `MAILJET_SECRET_KEY`, `KINDLE_EMAIL`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`.
