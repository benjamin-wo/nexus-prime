import { useEffect, useRef } from "react";

/** The Telegram Login Widget in redirect mode: Telegram sends the signed login to our callback.
 * `invite` is an app invite; `tripInvite` a trip's link, which the server joins them to as they sign in. */
export function TelegramLogin({ bot, invite, tripInvite }: { bot: string; invite?: string; tripInvite?: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const callback = new URL("/api/auth/telegram/callback", window.location.origin);
    if (invite) callback.searchParams.set("invite", invite);
    if (tripInvite) callback.searchParams.set("trip_invite", tripInvite);
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
  }, [bot, invite, tripInvite]);
  return <div ref={host} className="tg-login" aria-label="Sign in with Telegram" />;
}
