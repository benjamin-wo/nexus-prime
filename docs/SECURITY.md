# Security review (M10, 1 October 2026)

What Nexus protects, how, what this review changed, and what's left. Reviewed against the code at `86b1752`.

## What's at stake

A small number of invited people's money records: transactions, budgets, bills, IOUs, receipt photos, statements they import, connected mailboxes, and what Nexus remembers about them. The things that would hurt most: one user seeing or changing another's data, someone outside the allowlist getting in, credentials leaking (the bot token, API keys, Gmail refresh tokens), and the model being steered into changing data the user didn't ask to change.

## Controls in place

| Area | How |
|---|---|
| Who can use it | Telegram: only user ids on the allowlist (`TELEGRAM_ALLOWED_USER_IDS`) and the owner. Web: Telegram Login or Mini App signatures (HMAC with the bot token, checked in constant time, at most 24 hours old), and new people only through the owner's single-use, 24-hour invite links |
| Telegram webhook | Telegram's secret token header, compared in constant time; each update id is handled once |
| Sessions | Random tokens stored only as hashes; cookies `HttpOnly`, `Secure`, `SameSite=Lax` (`None; Partitioned` only inside the Telegram Mini App) |
| Cross-site requests | Every state-changing request must come from our origin and carry the session's CSRF token |
| One user's data from another's | Every query filters on the acting user; child rows reference their parent by `(id, user_id)`, so the database refuses cross-user links; tests try every use case as the wrong user |
| SQL injection | SQLAlchemy Core with bound parameters throughout; no SQL is built from user input |
| The model | It can only call tools, never SQL; tools act as the authenticated user, and any `user_id` it sends is dropped; changes ask the user to confirm; there's no tool that moves money; emails and receipts are read by separate, tool-less calls; memories come only from the user's own words and can't start a change |
| Secrets | From the environment only; Gmail refresh tokens encrypted with Fernet (`TOKEN_ENCRYPTION_KEY`, rotatable); access logs drop query strings on paths that carry one-time tokens |
| Files | Receipts in a private bucket behind links that expire in minutes; statements and their passwords are read for one request and never stored; CSV export neutralises cells a spreadsheet would run as formulas |
| Trip weather and place photos | Only a place's name and coordinates go to Open-Meteo; Google photo links are fetched without our key, image types only, under 2 MB, and never stored; both are capped or cached so a page can't run up requests |
| Trip photos | Only a place's name and a season leave for Wikipedia and the models, never anything of the user's; only Wikimedia https links are downloaded, JPEG, PNG or WebP under 4 MB; photos are shared across users by design (they're public, freely licensed images) and served by our own API, so the image policy stays `'self'` |
| Shared trip links | The one thing served without a sign-in. A link is 32 random bytes (`secrets.token_urlsafe`, 43 characters), one per trip, kept in `trip_shares`; the API returns an allow-list (destination, dates, day labels, the photo, and each scheduled entry's kind, title, airline or rail operator, times, legs, hotel, address and category), never money, booking references, where it was booked, notes, who's going, ids or anyone's account. A bad, unknown or stopped link all get the same 404; views are capped at 60 a minute and 2,000 a day per link; the page is `noindex`, and `Referrer-Policy: same-origin` keeps the link from leaking to Google Maps or fonts. The owner can make a new link (the old one stops) or stop sharing; deleting the trip deletes the link |
| Browser | A strict Content-Security-Policy on the web app, framing allowed only by Telegram's web client |
| Dependencies | `pip-audit` (272 locked packages) and `npm audit` (production): no known vulnerabilities |

## Fixed in this review

1. **No rate limits on what costs money.** A runaway client or a hijacked account could send messages to the model without limit. Now each user gets 20 messages a minute and 400 a day across Telegram and web chat (beyond that, a "give me a minute" reply that never reaches the model), and 30 statement previews or imports per 10 minutes (HTTP 429).
2. **API documentation was public.** `/docs`, `/redoc` and `/openapi.json` mapped every route in production; they're now off there.
3. **No cap on request size.** Any endpoint would read a body of any size before validating it. Bodies over 16 MB (a 10 MB PDF, base64-encoded, is the largest legitimate one) are refused with 413.
4. **Missing headers.** All responses now carry `X-Content-Type-Options: nosniff`, and `Strict-Transport-Security` over HTTPS; API responses also `Cache-Control: no-store` (money data stays out of browser and proxy caches) and `X-Frame-Options: DENY`.
5. **HTTP client logs.** httpx logs each request's URL at INFO, and Telegram's URLs contain the bot token. It was quiet only because nothing configured it; the HTTP client loggers are now held to warnings explicitly.
6. **A slow PDF could hold a request.** Reading a statement now gives up after 30 seconds.

## Known and accepted

- **Signed logins can be replayed for up to 24 hours** if someone captures one. That's Telegram's design; the window could be shortened at the cost of sign-ins from a stale page failing.
- **Rate limits are in memory**, per process: a restart resets them, and more than one instance would each count separately. Fine for one instance; move them to Postgres before scaling out.
- **The chat is kept for the web chat window**: the newest 500 lines per user (their messages and Nexus's replies; no images, emails or notifications), each user's alone.
- **The model provider sees what the model sees**: messages, the money snapshot, memories, and receipt and email text. OpenRouter's privacy settings exclude providers that train on prompts.
- **A thread that a crafted PDF ties up** keeps running after the 30-second limit returns; the size and page caps bound it.
- **The old database is kept read-only** for the legacy import; it's a separate Railway service and isn't reached at runtime.
- **A shared trip link works for whoever holds it.** It's a bearer link, like an unlisted photo album: anyone it's forwarded to can see the plan until the owner makes a new one or stops sharing. It shows only the plan (no money, references or notes), and it has no expiry by design, since companions come back to it during the trip.
