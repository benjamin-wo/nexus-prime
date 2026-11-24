import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button } from "../components/ui";
import { healthApi, healthKey } from "./api";
import { WellnessStatement } from "./WellnessStatement";

import "./health.css";

/** What Health stores and what it is not, in plain words. Shown before anything is kept. */
function ConsentScreen() {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function agree() {
    setBusy(true);
    setError(null);
    try {
      const consent = await healthApi.giveConsent();
      client.setQueryData(healthKey.consent, consent);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't turn on Health");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="health-consent">
      <div className="page-head">
        <div>
          <h1>Health</h1>
          <p className="muted">Log your workouts and see how you are progressing.</p>
        </div>
      </div>
      <section className="block" aria-labelledby="health-consent-title">
        <div className="block-head">
          <h2 id="health-consent-title">Before you start</h2>
        </div>
        <div className="card section-body health-prose">
          <p>
            Nexus will keep what you log in Health: your workouts, food logs, body weight and other measurements, and your
            health profile. It is used only to show your own history and progress, and it stays on your account.
          </p>
          <p>
            Health is for general wellness, not medical advice. It does not diagnose, treat or monitor any condition. Talk to a
            doctor before you change how you train if you have a health concern.
          </p>
          <p>You can turn Health off in Settings at any time. What you logged stays until you delete it.</p>
          <WellnessStatement />
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <Button variant="primary" full disabled={busy} onClick={() => void agree()}>
            Turn on Health
          </Button>
        </div>
      </section>
    </div>
  );
}

/** Shows its children once the person has agreed to Nexus keeping their health data, else the consent screen. */
export function HealthGate({ children }: { children: ReactNode }) {
  const consent = useQuery({ queryKey: healthKey.consent, queryFn: healthApi.consent });
  if (consent.isLoading) return <p className="state">Loading…</p>;
  if (consent.isError) return <LoadError variant="page" message="Couldn't load Health." query={consent} />;
  if (!consent.data?.consented_at) return <ConsentScreen />;
  return <>{children}</>;
}
