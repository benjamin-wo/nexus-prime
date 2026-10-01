import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type EmailConnection,
  type EmailOverview,
  type EmailStatus,
  type InboundEmail,
  type Me,
} from "../api";
import { formatDate } from "../format";

const LABELS: Record<EmailStatus, string> = {
  pending: "Waiting for you",
  logged: "Logged",
  skipped: "Skipped",
  not_receipt: "Not a receipt",
  no_amount: "No amount found",
  duplicate: "Already logged",
  failed: "Couldn't be read",
};

function EmailRow({ email, me, onChanged }: { email: InboundEmail; me: Me; onChanged: () => void }) {
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const needsAmount = !email.amount;

  async function act(path: string, body?: unknown) {
    setError(null);
    try {
      await api(`/email/${email.id}/${path}`, { method: "POST", body: body ?? {} });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't do that");
    }
  }

  function logWithAmount(event: FormEvent) {
    event.preventDefault();
    void act("log", { amount: amount.trim() });
  }

  return (
    <li className="budget email-row">
      <div className="budget-head">
        <h3 className="wrap">
          {email.received && email.merchant ? `From ${email.merchant}` : (email.merchant ?? email.subject)}
        </h3>
        {email.amount && (
          <span className={email.received ? "num amount-in" : "num"}>
            {email.received ? "+" : ""}
            {Number(email.amount).toFixed(2)} {email.currency}
          </span>
        )}
      </div>
      <p className="caption wrap">
        {email.sender} · {formatDate(email.received_at, me.user.timezone)}
        {email.merchant ? ` · ${email.subject}` : ""}
      </p>
      <div className="budget-foot">
        <span className={`caption email-status email-${email.status}`}>
          {LABELS[email.status]}
          {email.reason && email.status !== "pending" ? `: ${email.reason}` : ""}
        </span>
        {email.actionable && !needsAmount && (
          <span className="quick">
            <button type="button" className="btn btn-primary" onClick={() => act("log")}>
              Log it
            </button>
            {email.status === "pending" && (
              <button type="button" className="btn" onClick={() => act("skip")}>
                Skip
              </button>
            )}
          </span>
        )}
        {email.status === "logged" && email.transaction_id && (
          <Link className="caption" to="/ledger">
            In your ledger
          </Link>
        )}
      </div>
      {email.actionable && needsAmount && (
        <form className="quick email-amount" onSubmit={logWithAmount} aria-label={`Log ${email.subject}`}>
          <label className="field">
            Amount ({me.user.home_currency})
            <input
              className="input"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
          </label>
          <button type="submit" className="btn" disabled={!amount.trim()}>
            Log it
          </button>
        </form>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

function ConnectionRow({
  connection: c,
  me,
  confirming,
  onConfirm,
  onCancel,
  onDisconnect,
}: {
  connection: EmailConnection;
  me: Me;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onDisconnect: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const forward = c.provider === "forward";

  async function copy() {
    try {
      await navigator.clipboard.writeText(c.address);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  let seen = "Not checked yet";
  if (forward) {
    seen = c.last_received
      ? `Last email received ${formatDate(c.last_received, me.user.timezone)}`
      : "Nothing received yet";
  } else if (c.last_checked) {
    seen = `Last checked ${formatDate(c.last_checked, me.user.timezone)}`;
  }

  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">{c.address}</h3>
        <span className={`caption email-${c.status}`}>{c.status === "active" ? "Working" : "Needs reconnecting"}</span>
      </div>
      {forward && (
        <p className="caption">
          Your forwarding address: forward receipts here.{" "}
          <button type="button" className="btn btn-ghost" onClick={copy}>
            {copied ? "Copied" : "Copy address"}
          </button>
        </p>
      )}
      <div className="budget-foot">
        <span className="caption">{seen}</span>
        {confirming ? (
          <span className="quick">
            <span>{forward ? "Stop using this address?" : "Stop reading this mailbox?"}</span>
            <button type="button" className="btn btn-danger" onClick={onDisconnect}>
              Disconnect
            </button>
            <button type="button" className="btn" onClick={onCancel}>
              Keep
            </button>
          </span>
        ) : (
          <button type="button" className="btn btn-ghost" onClick={onConfirm}>
            Disconnect
          </button>
        )}
      </div>
    </li>
  );
}

/** Every email Nexus checked in the last 30 days, and what became of it. */
export function EmailPage({ me }: { me: Me }) {
  const client = useQueryClient();
  const overview = useQuery({ queryKey: ["email"], queryFn: () => api<EmailOverview>("/email") });
  const [confirming, setConfirming] = useState<string | null>(null);

  function refresh() {
    for (const key of ["email", "transactions", "summary"]) void client.invalidateQueries({ queryKey: [key] });
  }

  async function disconnect(id: string) {
    setConfirming(null);
    await api(`/email/connections/${id}`, { method: "DELETE" });
    refresh();
  }

  const data = overview.data;
  const waiting = data?.emails.filter((e) => e.status === "pending").length ?? 0;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Email</h1>
          <p className="muted">Receipts found in your email. Nothing is logged until you say so.</p>
        </div>
      </div>
      {overview.isLoading && <p className="state">Loading…</p>}
      {overview.isError && <p className="state error-text">Couldn't load your email.</p>}
      {data && data.connections.length === 0 && (
        <section className="card">
          <p className="state">
            No email is connected. To log receipts from email automatically, ask Nexus in chat: "how can I log my
            expenses automatically?"
          </p>
        </section>
      )}
      {data && data.connections.length > 0 && (
        <div className="plan-grid">
          <section className="card" aria-labelledby="mailboxes">
            <div className="card-head">
              <h2 id="mailboxes">Connected</h2>
            </div>
            <ul className="budgets">
              {data.connections.map((c) => (
                <ConnectionRow
                  key={c.id}
                  connection={c}
                  me={me}
                  confirming={confirming === c.id}
                  onConfirm={() => setConfirming(c.id)}
                  onCancel={() => setConfirming(null)}
                  onDisconnect={() => disconnect(c.id)}
                />
              ))}
            </ul>
            <p className="caption">
              Disconnecting removes Nexus's access (a forwarding address stops working). Expenses already logged
              stay.
            </p>
          </section>
          <section className="card" aria-labelledby="checked">
            <div className="card-head">
              <h2 id="checked">Checked emails</h2>
              <span className="caption">{waiting > 0 ? `${waiting} waiting for you` : "Last 30 days"}</span>
            </div>
            {data.emails.length === 0 ? (
              <p className="state">No receipt-like emails yet. New ones are checked every 15 minutes.</p>
            ) : (
              <ul className="budgets">
                {data.emails.map((e) => (
                  <EmailRow key={e.id} email={e} me={me} onChanged={refresh} />
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </>
  );
}

/** On the Settings page, only once a mailbox is connected. */
export function EmailCard() {
  const overview = useQuery({ queryKey: ["email"], queryFn: () => api<EmailOverview>("/email") });
  const data = overview.data;
  if (!data || data.connections.length === 0) return null;
  const waiting = data.emails.filter((e) => e.status === "pending").length;
  return (
    <section className="card" aria-labelledby="email-card">
      <div className="card-head">
        <h2 id="email-card">Email receipts</h2>
        <Link className="btn" to="/email">
          Open
        </Link>
      </div>
      <p className="caption">
        {data.connections.map((c) => c.address).join(", ")}
        {waiting > 0 ? ` · ${waiting} waiting for you` : ""}
      </p>
    </section>
  );
}
