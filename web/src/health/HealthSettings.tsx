import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmBox } from "../components/ConfirmBox";
import { LoadError } from "../components/LoadError";
import { Button, Section } from "../components/ui";
import { formatDate } from "../format";
import { healthApi, healthKey } from "./api";

/** Settings > Health data: whether Nexus keeps the person's workouts, and the way to take that back. */
export function HealthSettings() {
  const client = useQueryClient();
  const consent = useQuery({ queryKey: healthKey.consent, queryFn: healthApi.consent });
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const given = consent.data?.consented_at ?? null;

  async function withdraw() {
    setBusy(true);
    setError(null);
    try {
      await healthApi.withdrawConsent();
      client.setQueryData(healthKey.consent, { consented_at: null });
      setConfirming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't turn Health off");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section id="health-data" title="Health data">
      {consent.isError ? (
        <LoadError message="Couldn't load this." query={consent} />
      ) : consent.isLoading ? (
        <p className="state">Loading…</p>
      ) : given ? (
        <>
          <p>Nexus keeps your routines, plan, workouts and sets, from {formatDate(given)}. It is for general wellness, not medical advice.</p>
          <p className="caption">
            Turning Health off stops new workouts being kept. What you logged stays until you delete it.
          </p>
          {confirming ? (
            <ConfirmBox
              label="Turn off Health"
              question="Turn off Health? Nexus stops keeping new workouts."
              confirm="Turn off Health"
              busy={busy}
              onConfirm={() => void withdraw()}
              onKeep={() => setConfirming(false)}
            />
          ) : (
            <Button variant="danger" onClick={() => setConfirming(true)}>
              Turn off Health
            </Button>
          )}
        </>
      ) : (
        <p>
          Health is off. <Link to="/health">Turn it on</Link> when you want to log workouts.
        </p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Section>
  );
}
