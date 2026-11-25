import { HealthGate } from "./HealthGate";
import { TodayHint } from "./TodayHint";
import { TodayMeals } from "./TodayMeals";
import { TodayWeight } from "./TodayWeight";
import { TodayWorkout } from "./TodayWorkout";

/** Health's Today: a daily log. Most logging happens in chat; this shows what is in it. */
export function HealthHome({ onOpenChat }: { onOpenChat?: () => void }) {
  return (
    <HealthGate>
      <div className="page-head">
        <div>
          <h1>Health</h1>
        </div>
      </div>
      <TodayHint onOpenChat={onOpenChat} />
      <TodayMeals />
      <TodayWorkout onOpenChat={onOpenChat} />
      <TodayWeight />
    </HealthGate>
  );
}
