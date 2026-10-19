import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { TelegramLogin } from "../components/TelegramLogin";
import { initData, miniApp } from "../telegram";

const ERRORS: Record<string, string> = {
  signin: "That sign-in couldn't be verified. Please try again.",
  access: "You need an invite to use the web app. Ask the owner for a link.",
};

/** What the server's sign-in says about a trip invite it refused. */
const TRIP_ACCESS =
  "That invite couldn't be used. It may have been used already or expired, or you may need an app invite. Ask the trip's owner for a new link.";

/** Telegram's widget sends a refused sign-in to /login?error=access, away from the invite page.
 * The invite page leaves this note so the sign-in page can say it was a trip invite. */
const TRIP_NOTE = "nexus:trip-invite";
function tripNote(action: "get" | "set" | "clear"): boolean {
  try {
    if (action === "set") sessionStorage.setItem(TRIP_NOTE, "1");
    else if (action === "clear") sessionStorage.removeItem(TRIP_NOTE);
    else return sessionStorage.getItem(TRIP_NOTE) === "1";
  } catch {
    // Storage can be blocked; the plain message still shows.
  }
  return false;
}
/** Called when someone is signed in and the note is no longer needed. */
export const forgetTripNote = () => tripNote("clear");

/** The sign-in page. With `trip`, the page is for a trip invite (`/trip-invite/:token`): the same
 * Telegram sign-in, carrying the trip's link so the server puts them on the trip. */
export function LoginPage({ trip = false }: { trip?: boolean }) {
  const { token } = useParams();
  const [search] = useSearchParams();
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () => api<{ bot_username: string }>("/config"),
  });
  const [afterTrip] = useState(() => !trip && tripNote("get"));
  useEffect(() => {
    if (trip) tripNote("set");
    else tripNote("clear");
  }, [trip]);

  // Inside Telegram the widget can't help: the launch data already said who this is, and the Mini App
  // sign-in carried the trip invite too. So the page only shows up when that sign-in was refused.
  let error: string | undefined;
  if (initData) {
    if (miniApp.error === "access") error = trip ? TRIP_ACCESS : ERRORS.access;
    else error = "Sign-in failed. Close and reopen the app.";
  } else {
    const code = search.get("error") ?? "";
    error = code === "access" && afterTrip ? TRIP_ACCESS : ERRORS[code];
  }
  return (
    <div className="login">
      <section className="card">
        {trip ? (
          <>
            <p className="caption">
              Nexus <span style={{ color: "var(--accent)" }}>Prime</span>
            </p>
            <h1>You've been invited to a trip</h1>
            {!initData && <p className="secondary">Sign in with Telegram to join.</p>}
          </>
        ) : (
          <>
            <h1>
              Nexus <span style={{ color: "var(--accent)" }}>Prime</span>
            </h1>
            <p className="secondary">
              {token ? "You've been invited. Sign in with Telegram to accept." : "Sign in with your Telegram account."}
            </p>
          </>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {initData ? null : config.data ? (
          <TelegramLogin bot={config.data.bot_username} invite={trip ? undefined : token} tripInvite={trip ? token : undefined} />
        ) : config.isError ? (
          <p className="error-text">Sign-in isn't available right now.</p>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </section>
    </div>
  );
}
