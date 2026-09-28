import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { TelegramLogin } from "../components/TelegramLogin";

const ERRORS: Record<string, string> = {
  signin: "That sign-in couldn't be verified. Please try again.",
  access: "You need an invite to use the web app. Ask the owner for a link.",
};

export function LoginPage() {
  const { token } = useParams();
  const [search] = useSearchParams();
  const config = useQuery({ queryKey: ["config"], queryFn: () => api<{ bot_username: string }>("/config") });
  const error = ERRORS[search.get("error") ?? ""];
  return (
    <div className="login">
      <section className="card">
        <h1>
          Nexus <span style={{ color: "var(--orange-primary)" }}>Prime</span>
        </h1>
        <p className="secondary">
          {token ? "You've been invited. Sign in with Telegram to accept." : "Sign in with your Telegram account."}
        </p>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {config.data ? (
          <TelegramLogin bot={config.data.bot_username} invite={token} />
        ) : config.isError ? (
          <p className="error-text">Sign-in isn't available right now.</p>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </section>
    </div>
  );
}
