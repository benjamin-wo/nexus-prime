import { useEffect, useState } from "react";

import { nativeHaptic } from "../native";
import { Button } from "../components/ui";
import { formatClockSeconds } from "./format";

const say = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return [m ? `${m} ${m === 1 ? "minute" : "minutes"}` : "", s ? `${s} seconds` : ""].filter(Boolean).join(" ");
};

/**
 * The rest between sets. The clock on screen is silent for screen readers (it would read out every second); a polite
 * live region says when the rest starts, at every 30 seconds, at 10 seconds left and when it is over. The end gives
 * a light haptic in the app. `run` changes with every set, which starts the rest again.
 */
export function RestTimer({ seconds, run, onSkip }: { seconds: number; run: number; onSkip: () => void }) {
  const [left, setLeft] = useState(seconds);
  const [said, setSaid] = useState("");

  useEffect(() => {
    const end = Date.now() + seconds * 1000;
    setLeft(seconds);
    setSaid(`Rest ${say(seconds)}.`);
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) {
        window.clearInterval(timer);
        setSaid("Rest is over.");
        nativeHaptic("light");
      } else if (remaining === 10 || remaining % 30 === 0) {
        setSaid(`${say(remaining)} left.`);
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [seconds, run]);

  const over = left === 0;
  return (
    <div className="health-rest" role="group" aria-label="Rest timer">
      <span className="health-rest-clock health-fig" aria-hidden="true">
        {formatClockSeconds(left)}
      </span>
      <span className="health-rest-label" aria-hidden="true">
        {over ? "Rest is over" : "Rest"}
      </span>
      <p className="sr-only" role="status" aria-live="polite">
        {said}
      </p>
      <Button size="sm" onClick={onSkip}>
        {over ? "Hide" : "Skip rest"}
      </Button>
    </div>
  );
}
