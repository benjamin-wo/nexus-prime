import { Figure } from "./ui";

/** A large figure as a card of its own, a region named by its label (Dashboard and Costs tiles). */
export function StatTile({ label, value, extra }: { label: string; value: string; extra?: string }) {
  return <Figure as="section" className="card" aria-label={label} label={label} value={value} extra={extra} />;
}
