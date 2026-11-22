import { useCallback, useEffect, useRef, useState } from "react";

import { type DevicePoll, type DeviceStart, api, ApiError } from "../api";
import { Button, ButtonLink } from "./ui";

import "../pages/settings.css";

const POLL_MS = 2000;

type State =
  | { kind: "loading" }
  | { kind: "ready"; start: DeviceStart; expiresAt: number }
  | { kind: "expired" }
  | { kind: "failed" };

/** Sign-in inside the iOS app: shows a code to approve in Telegram, polls until the bot's Yes comes
 * through, then opens the one-time sign-in link the server hands over. */
export function AppSignIn({
  pollMs = POLL_MS,
  navigate = (path: string) => window.location.assign(path),
}: {
  pollMs?: number;
  navigate?: (path: string) => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [left, setLeft] = useState(0);
  const [round, setRound] = useState(0);
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  // One code per round; "Get a new code" starts the next.
  useEffect(() => {
    const abort = new AbortController();
    setState({ kind: "loading" });
    api<DeviceStart>("/auth/device", { method: "POST", signal: abort.signal }).then(
      (start) => {
        setLeft(start.expires_in);
        setState({ kind: "ready", start, expiresAt: Date.now() + start.expires_in * 1000 });
      },
      () => {
        if (!abort.signal.aborted) setState({ kind: "failed" });
      },
    );
    return () => abort.abort();
  }, [round]);

  const poll_id = state.kind === "ready" ? state.start.poll_id : null;
  const expiresAt = state.kind === "ready" ? state.expiresAt : 0;

  useEffect(() => {
    if (!poll_id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();
    const tick = async () => {
      try {
        const answer = await api<DevicePoll>(`/auth/device/${encodeURIComponent(poll_id)}`, { signal: abort.signal });
        if (stopped) return;
        if (answer.status === "approved") {
          stopped = true;
          navigateRef.current(answer.login_path);
          return;
        }
      } catch (e) {
        if (stopped) return;
        if (e instanceof ApiError && e.status === 404) {
          setState({ kind: "expired" });
          return;
        }
        // A dropped connection or a 429: try again on the next beat.
      }
      timer = setTimeout(tick, pollMs);
    };
    timer = setTimeout(tick, pollMs);
    return () => {
      stopped = true;
      abort.abort();
      clearTimeout(timer);
    };
  }, [poll_id, pollMs]);

  useEffect(() => {
    if (!poll_id) return;
    const update = () => {
      const remaining = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) setState({ kind: "expired" });
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [poll_id, expiresAt]);

  const again = useCallback(() => setRound((n) => n + 1), []);

  if (state.kind === "loading") return <p className="muted">Getting a sign-in code…</p>;
  if (state.kind === "failed") {
    return (
      <div className="app-signin">
        <p className="error-text" role="alert">
          Couldn't get a sign-in code. Check your connection and try again.
        </p>
        <Button onClick={again}>
          Try again
        </Button>
      </div>
    );
  }
  if (state.kind === "expired") {
    return (
      <div className="app-signin">
        <p className="secondary">That code has expired.</p>
        <Button variant="primary" onClick={again}>
          Get a new code
        </Button>
      </div>
    );
  }
  const { code, bot_username: bot } = state.start;
  const plain = code.replace("-", "");
  const minutes = Math.floor(left / 60);
  return (
    <div className="app-signin">
      <p className="secondary">Approve this code in Telegram to sign in.</p>
      <p className="app-signin-code" aria-label={`Sign-in code ${code}`}>
        {code}
      </p>
      <ButtonLink variant="primary" className="landing-cta" href={`https://t.me/${bot}?start=app-${plain}`}>
        Open Telegram
      </ButtonLink>
      <p className="secondary">
        Or send <span className="num">/app {code}</span> to @{bot}
      </p>
      <p className="muted num">
        {`Expires in ${minutes}:${String(left % 60).padStart(2, "0")}`}
      </p>
    </div>
  );
}
