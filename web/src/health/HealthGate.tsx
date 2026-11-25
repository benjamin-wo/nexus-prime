import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button } from "../components/ui";
import { healthApi, healthKey } from "./api";
import { bodyApi, bodyKey } from "./bodyApi";
import { useConsents } from "./bodyHooks";
import { WellnessStatement } from "./WellnessStatement";

import "./health.css";

/** One screen, plain words, one button. The separate switches live in Settings, under Health data. */
function ConsentScreen() {
  const client = useQueryClient();
  const consents = useConsents();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const provider = consents.data?.ai_provider;

  async function turnOn() {
    setBusy(true);
    setError(null);
    try {
      const state = await bodyApi.turnOn();
      client.setQueryData(bodyKey.consents, state);
      client.setQueryData(healthKey.consent, { consented_at: state.health_consented_at });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't turn on Health");
      setBusy(false);
    }
  }

  return (
    <div className="health-consent">
      <div className="page-head">
        <div>
          <h1>Health</h1>
          <p className="muted">Log food, workouts and weight by chat or here.</p>
        </div>
      </div>
      <section className="block" aria-labelledby="health-consent-title">
        <div className="block-head">
          <h2 id="health-consent-title">Before you start</h2>
        </div>
        <div className="card section-body health-prose">
          <p>Nexus keeps what you log: your food, workouts and weight. It stays on your account.</p>
          <p>
            Nexus's AI reads it to answer you
            {provider ? `, through ${provider.name} in ${inCountry(provider.country)}` : ""}.
          </p>
          <p>It is for general wellness, not medical advice.</p>
          <WellnessStatement />
          <p className="caption">You can change these choices in Settings, under Health data.</p>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <Button variant="primary" full disabled={busy} onClick={() => void turnOn()}>
            Turn on Health
          </Button>
        </div>
      </section>
    </div>
  );
}

/** Shows its children once Health is on, else the consent screen. */
/** "in the United States", "in Germany": names that start with "United" take "the". */
const inCountry = (country: string) => (country.startsWith("United") ? `the ${country}` : country);

export function HealthGate({ children }: { children: ReactNode }) {
  const consent = useQuery({ queryKey: healthKey.consent, queryFn: healthApi.consent });
  if (consent.isLoading) return <p className="state">Loading…</p>;
  if (consent.isError) return <LoadError variant="page" message="Couldn't load Health." query={consent} />;
  if (!consent.data?.consented_at) return <ConsentScreen />;
  return <>{children}</>;
}
