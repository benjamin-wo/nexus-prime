import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { api } from "../api";

/**
 * Opened from a one-time link (often in the phone's browser, from Telegram), so it
 * works without signing in. It says whose Nexus account the mailbox will join, so
 * nobody connects their mail to a link someone else sent them.
 */
export function ConnectGmail() {
  const [params] = useSearchParams();
  const token = params.get("t") ?? "";
  const link = useQuery({
    queryKey: ["email-link", token],
    queryFn: () =>
      api<{ valid: boolean; account_hint: string | null }>(`/email/link?t=${encodeURIComponent(token)}`),
    enabled: Boolean(token),
    retry: false,
  });

  return (
    <main className="connect">
      <section className="card connect-card" aria-labelledby="connect-title">
        <h1 id="connect-title">Connect Gmail</h1>
        {link.isLoading && <p className="state">Checking your link…</p>}
        {(!token || link.isError || link.data?.valid === false) && (
          <p className="state">This link has expired or was already used. Ask Nexus for a new one.</p>
        )}
        {link.data?.valid && (
          <>
            <p>
              Nexus will look for receipts in your Gmail and ask you before logging each one. It only reads emails that
              look like receipts, invoices, orders or card alerts.
            </p>
            <p className="caption">
              This adds the mailbox to the Nexus account of Telegram user …{link.data.account_hint}. If someone else
              sent you this link, close this page.
            </p>
            <ol className="connect-steps">
              <li>Pick your Google account.</li>
              <li>
                Google will say <strong>Google hasn't verified this app</strong>, because Nexus is a private app. Tap{" "}
                <strong>Advanced</strong>, then <strong>Go to Nexus</strong>.
              </li>
              <li>
                Tap <strong>Allow</strong>.
              </li>
            </ol>
            <a className="btn btn-primary" href={`/api/email/gmail/start?t=${encodeURIComponent(token)}`}>
              Continue to Google
            </a>
          </>
        )}
      </section>
    </main>
  );
}

const PROBLEMS: Record<string, string> = {
  expired: "This link has expired or was already used. Ask Nexus for a new one.",
  declined: "Nothing was connected, because Google's sign-in was cancelled.",
  permission: "Nothing was connected: Nexus needs permission to read your email to find receipts.",
};

export function ConnectDone() {
  const [params] = useSearchParams();
  const error = params.get("error");
  return (
    <main className="connect">
      <section className="card connect-card" aria-labelledby="done-title">
        <h1 id="done-title">{error ? "Not connected" : "Gmail connected"}</h1>
        {error ? (
          <p>{PROBLEMS[error] ?? PROBLEMS.declined}</p>
        ) : (
          <p>
            You're all set. Nexus is looking for receipts from the last 30 days and will message you in Telegram.
            Nothing is logged until you confirm it. You can close this page.
          </p>
        )}
      </section>
    </main>
  );
}
