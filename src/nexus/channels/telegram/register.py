"""python -m nexus.channels.telegram.register [--url URL] [--yes]

Point the bot at a webhook URL. By default: this service's public domain
(RAILWAY_PUBLIC_DOMAIN) + /telegram/webhook. It prints the current webhook first;
running it again with --url set to the old address is the rollback.
"""

import argparse
import asyncio
import os
import sys

import httpx

from nexus.channels.telegram.client import HttpTelegramClient
from nexus.settings import Settings


def default_url() -> str | None:
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{domain}/telegram/webhook" if domain else None


async def main(argv: list[str], http: httpx.AsyncClient | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nexus.channels.telegram.register")
    parser.add_argument("--url", help="webhook URL (default: this service's public domain)")
    parser.add_argument("--yes", action="store_true", help="change it (default: only show)")
    args = parser.parse_args(argv)

    settings = Settings()
    if settings.telegram_bot_token is None or settings.telegram_webhook_secret is None:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET must be set", file=sys.stderr)
        return 2
    url = args.url or default_url()
    if not url or not url.startswith("https://"):
        print("need an https:// --url (RAILWAY_PUBLIC_DOMAIN is not set)", file=sys.stderr)
        return 2

    async with http or httpx.AsyncClient() as client_http:
        client = HttpTelegramClient(settings.telegram_bot_token.get_secret_value(), client_http)
        current = await client.webhook_info()
        print(f"current webhook: {current.get('url') or '(none)'}")
        print(f"pending updates: {current.get('pending_update_count', 0)}")
        if current.get("last_error_message"):
            print(f"last error: {current['last_error_message']}")
        if not args.yes:
            print(f"would set: {url}  (re-run with --yes to change it)")
            return 0
        await client.set_webhook(url, settings.telegram_webhook_secret.get_secret_value())
        print(f"webhook set: {(await client.webhook_info()).get('url')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
