import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmBox } from "../components/ConfirmBox";
import { LoadError } from "../components/LoadError";
import { Button, Row, RowList, Section } from "../components/ui";
import { formatDate } from "../format";
import { healthApi, healthKey, type WeightUnit } from "./api";
import { useProfile } from "./bodyHooks";
import { ConsentSwitches } from "./ConsentSwitches";
import { ProfileSheet } from "./ProfileSheet";
import { Signposts, TargetsPaused } from "./SafetyNotes";
import { reasonText } from "./safety";
import { WellnessStatement } from "./WellnessStatement";

/** kg or lb for the weights logged in a workout. Needs no consent; quiet if it can't load. */
function WeightUnitChoice() {
  const client = useQueryClient();
  const prefs = useQuery({ queryKey: healthKey.preferences, queryFn: healthApi.preferences });
  const [error, setError] = useState<string | null>(null);
  if (!prefs.data) return null;
  const choose = async (unit: WeightUnit) => {
    setError(null);
    try {
      client.setQueryData(healthKey.preferences, await healthApi.setPreferences(unit));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    }
  };
  return (
    <div role="group" aria-label="Weight unit">
      <p className="caption">Log weights in</p>
      {(["kg", "lb"] as const).map((u) => (
        <Button key={u} variant={prefs.data.unit === u ? "primary" : undefined} aria-pressed={prefs.data.unit === u} onClick={() => void choose(u)}>
          {u}
        </Button>
      ))}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** Your profile, what the safety rules did with it in plain sentences, and the way to change it. */
function ProfileRow() {
  const profile = useProfile();
  const [open, setOpen] = useState(false);
  const p = profile.data;
  const lines = (p?.safety.gates ?? []).map((g) => reasonText(g.reason)).filter(Boolean);
  return (
    <>
      <RowList aria-label="Profile">
        <Row
          title="Profile and targets"
          sub={p ? "Birth year, height, activity, goal and privacy" : "Not set up yet"}
          label="Open profile and targets"
          onClick={() => setOpen(true)}
        />
      </RowList>
      {lines.map((l) => (
        <p key={l} className="caption">
          {l}
        </p>
      ))}
      {p?.safety.suspended && <TargetsPaused safety={p.safety} />}
      {p && !p.safety.suspended && <Signposts items={p.safety.signposts} />}
      {open && <ProfileSheet profile={p} onClose={() => setOpen(false)} />}
    </>
  );
}

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
      <WeightUnitChoice />
      {consent.isError ? (
        <LoadError message="Couldn't load this." query={consent} />
      ) : consent.isLoading ? (
        <p className="state">Loading…</p>
      ) : given ? (
        <>
          <p>Nexus keeps your workouts, food logs, body weight and other measurements, and your health profile, from {formatDate(given)}. It is for general wellness, not medical advice.</p>
          <p className="caption">
            Turning Health off stops new entries being kept. What you logged stays until you delete it.
          </p>
          <ConsentSwitches />
          <ProfileRow />
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
      <WellnessStatement />
    </Section>
  );
}
