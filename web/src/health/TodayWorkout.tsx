import { useQuery } from "@tanstack/react-query";

import { LoadError } from "../components/LoadError";
import { Row, RowList, Section } from "../components/ui";
import { healthApi, healthKey } from "./api";

/** Today's workout: Start or Resume (in Gym), or ask Nexus for one. */
export function TodayWorkout({ onOpenChat }: { onOpenChat?: () => void }) {
  const today = useQuery({ queryKey: [...healthKey.all, "today"], queryFn: healthApi.today });
  if (today.isError) return <LoadError message="Couldn't load today's workout." query={today} />;
  if (!today.data) return <p className="state">Loading…</p>;
  const { in_progress: open, routine } = today.data;
  const planned = open?.planned_slots?.length ?? 0;
  const count = routine?.slots.length ?? planned;
  return (
    <Section id="home-workout" title="Workout">
      <RowList aria-label="Workout">
        {open || routine ? (
          <Row
            to="/health/gym"
            title={open ? "Workout in progress" : (routine?.name ?? "Workout")}
            sub={open ? "Pick up where you left off" : `${count} ${count === 1 ? "exercise" : "exercises"}`}
            trailing={open ? "Resume" : "Start"}
          />
        ) : (
          <Row title="Ask Nexus for a workout" label="Ask Nexus for a workout" onClick={onOpenChat} />
        )}
      </RowList>
    </Section>
  );
}
