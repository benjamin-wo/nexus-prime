import { useConsents } from "./bodyHooks";

/** The wellness statement, verbatim from the API. Nothing while it loads or if it can't. */
export function WellnessStatement() {
  const consents = useConsents();
  if (!consents.data) return null;
  return <p className="caption health-statement">{consents.data.wellness_statement}</p>;
}
