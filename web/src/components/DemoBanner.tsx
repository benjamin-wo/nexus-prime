import { useEffect, useState } from "react";

import { timeLeft } from "../demo";

const DISMISSED = "nexus:demo-banner-dismissed";

function wasDismissed(): boolean {
  try {
    return sessionStorage.getItem(DISMISSED) === "1";
  } catch {
    return false; // Storage can be blocked; the bar just shows again.
  }
}

/** The slim bar over the app while the visitor is in the public demo: what it is, how long it lasts and a
 * way out to a real account. Closing it lasts for the browser session. */
export function DemoBanner({ expiresAt, onSignIn }: { expiresAt: string; onSignIn: () => void }) {
  const [hidden, setHidden] = useState(wasDismissed);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(tick);
  }, []);
  if (hidden) return null;
  return (
    <div className="demo-banner" role="region" aria-label="Demo account">
      <p>
        <strong>Demo</strong> · made-up data · resets in {timeLeft(expiresAt, now)} ·{" "}
        <button type="button" className="demo-banner-link" onClick={onSignIn}>
          Sign in with Telegram
        </button>{" "}
        to use your own
      </p>
      <button
        type="button"
        className="demo-banner-close"
        aria-label="Dismiss demo notice"
        onClick={() => {
          setHidden(true);
          try {
            sessionStorage.setItem(DISMISSED, "1");
          } catch {
            // Hidden for now; that's all that's lost.
          }
        }}
      >
        ×
      </button>
    </div>
  );
}
