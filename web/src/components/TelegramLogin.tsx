import { useEffect, useRef } from "react";

/** The Telegram Login Widget in redirect mode: Telegram sends the signed login to our callback. */
export function TelegramLogin({ bot, invite }: { bot: string; invite?: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const callback = new URL("/api/auth/telegram/callback", window.location.origin);
    if (invite) callback.searchParams.set("invite", invite);
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.dataset.telegramLogin = bot;
    script.dataset.size = "large";
    script.dataset.radius = "8";
    script.dataset.authUrl = callback.toString();
    script.dataset.requestAccess = "write";
    node.replaceChildren(script);
    return () => node.replaceChildren();
  }, [bot, invite]);
  return <div ref={host} className="tg-login" aria-label="Sign in with Telegram" />;
}
