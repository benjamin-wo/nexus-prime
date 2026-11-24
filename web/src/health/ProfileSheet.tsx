import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Sheet } from "../components/Sheet";
import { Button, Chip, ChipGroup } from "../components/ui";
import { type ActivityLevel, bodyApi, bodyKey, type Goal, type Profile, type Sex } from "./bodyApi";
import { Signposts } from "./SafetyNotes";
import { reasonText } from "./safety";
import { healthKey } from "./api";

const SEX: [Sex, string][] = [["female", "Female"], ["male", "Male"], ["unspecified", "Prefer not to say"]];
const ACTIVITY: [ActivityLevel, string][] = [
  ["sedentary", "Mostly sitting"],
  ["light", "Lightly active"],
  ["moderate", "Moderately active"],
  ["active", "Active"],
  ["very_active", "Very active"],
];
const GOALS: [Goal, string][] = [["lose", "Lose weight"], ["maintain", "Maintain"], ["gain", "Gain"], ["performance", "Performance"]];
const RATES = ["0.25", "0.5", "0.75"];

/** After saving: what the safety rules did, in plain sentences, and where to get help. */
function Outcome({ profile }: { profile: Profile }) {
  const lines = profile.safety.gates.map((g) => reasonText(g.reason)).filter(Boolean);
  return (
    <div className="health-stack" role="status">
      <p>Saved.</p>
      {lines.map((l) => (
        <p key={l}>{l}</p>
      ))}
      <Signposts items={profile.safety.signposts} />
    </div>
  );
}

/** The wellness profile: what the energy estimates use, the goal and rate, and the two privacy switches. */
export function ProfileSheet({ profile, onClose }: { profile: Profile | null | undefined; onClose: () => void }) {
  const client = useQueryClient();
  const [birth, setBirth] = useState(profile?.birth_year ? String(profile.birth_year) : "");
  const [height, setHeight] = useState(profile?.height_cm ?? "");
  const [sex, setSex] = useState<Sex>(profile?.sex_for_equations ?? "unspecified");
  const [activity, setActivity] = useState<ActivityLevel | "">(profile?.activity_level ?? "");
  const [goal, setGoal] = useState<Goal>(profile?.goal ?? "maintain");
  const [rate, setRate] = useState(profile?.target_rate_pct_per_week ?? "");
  const [numbersFree, setNumbersFree] = useState(profile?.numbers_free ?? false);
  const [ed, setEd] = useState(profile?.ed_history ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Profile | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await bodyApi.saveProfile({
        sex_for_equations: sex,
        birth_year: birth.trim() ? Number(birth) : null,
        height_cm: height.trim() || null,
        activity_level: activity || null,
        goal,
        target_rate_pct_per_week: goal === "maintain" || goal === "performance" ? null : rate || null,
        numbers_free: numbersFree,
        ed_history: ed,
        unit_system: profile?.unit_system ?? "metric",
      });
      client.setQueryData(bodyKey.profile, out);
      await client.invalidateQueries({ queryKey: healthKey.all });
      setSaved(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your profile");
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <Sheet title="Profile and targets" onClose={onClose} footer={<Button variant="primary" full onClick={onClose}>Done</Button>}>
        <Outcome profile={saved} />
      </Sheet>
    );
  }
  return (
    <Sheet
      title="Profile and targets"
      as="form"
      onSubmit={(e) => void save(e)}
      onClose={onClose}
      footer={
        <Button variant="primary" full type="submit" disabled={busy}>
          Save profile
        </Button>
      }
    >
      <div className="health-stack">
        <p className="caption">Birth year, height and sex are only used for energy estimates.</p>
        <div className="health-fields health-fields-2">
          <label className="field">
            Birth year
            <input className="input health-fig" type="number" inputMode="numeric" min="1900" max="2100" value={birth} onChange={(e) => setBirth(e.target.value)} />
          </label>
          <label className="field">
            Height (cm)
            <input className="input health-fig" type="number" inputMode="decimal" min="50" max="260" step="any" value={height} onChange={(e) => setHeight(e.target.value)} />
          </label>
        </div>
        <ChipGroup role="radiogroup" aria-label="Sex for equations">
          {SEX.map(([v, label]) => (
            <Chip key={v} pressed={sex === v} role="radio" aria-checked={sex === v} onClick={() => setSex(v)}>
              {label}
            </Chip>
          ))}
        </ChipGroup>
        <label className="field">
          Activity level
          <select className="input" value={activity} onChange={(e) => setActivity(e.target.value as ActivityLevel | "")}>
            <option value="">Not set</option>
            {ACTIVITY.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <ChipGroup role="radiogroup" aria-label="Goal">
          {GOALS.map(([v, label]) => (
            <Chip key={v} pressed={goal === v} role="radio" aria-checked={goal === v} onClick={() => setGoal(v)}>
              {label}
            </Chip>
          ))}
        </ChipGroup>
        {(goal === "lose" || goal === "gain") && (
          <ChipGroup role="radiogroup" aria-label="Rate, percent of body weight a week">
            {RATES.map((r) => (
              <Chip key={r} pressed={rate === r} role="radio" aria-checked={rate === r} onClick={() => setRate(r)}>
                {`${r} % a week`}
              </Chip>
            ))}
          </ChipGroup>
        )}
        <label className="share-switch">
          <input type="checkbox" role="switch" checked={numbersFree} onChange={(e) => setNumbersFree(e.target.checked)} />
          <span>Hide numbers (show words instead of calories and weights)</span>
        </label>
        <label className="share-switch">
          <input type="checkbox" role="switch" checked={ed} onChange={(e) => setEd(e.target.checked)} />
          <span>I have a history of an eating disorder</span>
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </Sheet>
  );
}
