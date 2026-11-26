import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Row, RowList, Section } from "../components/ui";
import { formatShortDate, shiftDay } from "../format";
import { healthApi, healthKey } from "./api";
import { BodyMap } from "./body/BodyMap";
import { formatVolume } from "./format";

/** Working sets per muscle for one week: a body map (worked this week is solid, only helped is lighter) and the list. */
export function VolumeView() {
  const [week, setWeek] = useState<string | undefined>(undefined);
  const volume = useQuery({ queryKey: [...healthKey.all, "volume", week], queryFn: () => healthApi.volume(week) });
  const start = volume.data?.week_start;
  const worked = (volume.data?.muscles ?? []).filter((m) => m.sets > 0);
  const helped = (volume.data?.muscles ?? []).filter((m) => m.sets === 0 && m.secondary_sets > 0);
  return (
    <Section
      id="volume"
      title="Sets this week"
      action={
        start && (
          <span className="quick">
            <Button variant="text" size="sm" onClick={() => setWeek(shiftDay(start, -7))}>
              Earlier week
            </Button>
            <Button variant="text" size="sm" onClick={() => setWeek(shiftDay(start, 7))}>
              Later week
            </Button>
          </span>
        )
      }
    >
      {volume.isError ? (
        <LoadError message="Couldn't load this week." query={volume} />
      ) : !volume.data ? (
        <p className="state">Loading…</p>
      ) : (
        <>
          <p className="caption">Week of {formatShortDate(`${volume.data.week_start}T00:00:00Z`, "UTC")}</p>
          {volume.data.muscles.length === 0 ? (
            <p className="muted">No sets this week.</p>
          ) : (
            <>
              <div className="health-body-map">
                <BodyMap view="both" primary={worked.map((m) => m.muscle)} secondary={helped.map((m) => m.muscle)} />
              </div>
              <RowList aria-label="Sets per muscle">
                {volume.data.muscles.map((m) => (
                  <Row
                    key={m.muscle}
                    title={m.muscle}
                    sub={`${formatVolume(m.volume_kg)}${m.secondary_sets ? ` · ${m.secondary_sets} more as a helper` : ""}`}
                    trailing={<span className="health-fig">{m.sets} {m.sets === 1 ? "set" : "sets"}</span>}
                  />
                ))}
              </RowList>
            </>
          )}
        </>
      )}
    </Section>
  );
}
