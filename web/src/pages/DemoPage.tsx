import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api";
import { Kaya } from "../components/Kaya";
import { TelegramLogin } from "../components/TelegramLogin";

type Step = "working" | "off" | "limited" | "error";

/** Sign in with Telegram, as the sign-in page offers it. */
function TelegramSignIn() {
  const config = useQuery({ queryKey: ["config"], queryFn: () => api<{ bot_username: string }>("/config") });
  if (config.data) return <TelegramLogin bot={config.data.bot_username} />;
  if (config.isError) return <p className="error-text">Sign-in isn't available right now.</p>;
  return <p className="muted">Loading…</p>;
}

/** `/demo`, the link on the resume: starts a private demo account and drops the visitor on Home.
 * (Someone already signed in never gets here; the app sends them to Home instead.) */
export function DemoPage() {
  const client = useQueryClient();
  const [step, setStep] = useState<Step>("working");
  const [attempt, setAttempt] = useState(0);
  // One demo per attempt, even when React runs effects twice in development.
  const started = useRef(-1);

  useEffect(() => {
    if (started.current === attempt) return;
    started.current = attempt;
    void (async () => {
      try {
        await api("/demo", { method: "POST" });
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) setStep("off");
        else if (e instanceof ApiError && e.status === 429) setStep("limited");
        else setStep("error");
        return;
      }
      // The session cookie is set: learn who we are. The app then sends /demo on to Home, replacing it
      // in the history. If we still don't know, the demo can't be used, so say so and offer a retry.
      await client.refetchQueries({ queryKey: ["me"] });
      if (!client.getQueryData(["me"])) setStep("error");
    })();
  }, [attempt, client]);

  return (
    <div className="login">
      <section className="card" aria-live="polite">
        <Kaya big size={150} className="kaya-hero" />
        <p className="caption">
          Just ask <span style={{ color: "var(--accent)" }}>Kaya</span>
        </p>
        {step === "working" && (
          <>
            <h1>Setting up your demo…</h1>
            <p className="secondary">A private account with made-up data, just for you.</p>
          </>
        )}
        {step === "off" && (
          <>
            <h1>The demo is resting right now</h1>
            <p className="secondary">Please check back later, or sign in if you already have an account.</p>
            <TelegramSignIn />
          </>
        )}
        {step === "limited" && (
          <>
            <h1>Too many demos from this network</h1>
            <p className="secondary">Too many demos from this network — try again in a bit.</p>
          </>
        )}
        {step === "error" && (
          <>
            <h1>Couldn't set up the demo</h1>
            <p className="secondary">Check your connection and try again.</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setStep("working");
                setAttempt((n) => n + 1);
              }}
            >
              Try again
            </button>
          </>
        )}
      </section>
    </div>
  );
}
