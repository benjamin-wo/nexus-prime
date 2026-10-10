import { CountUp } from "../motion";

export function StatTile({ label, value, extra }: { label: string; value: string; extra?: string }) {
  return (
    <section className="card tile" aria-label={label}>
      <div className="caption">{label}</div>
      <div className="value">
        <CountUp value={value} />
      </div>
      {extra && <div className="extra">{extra}</div>}
    </section>
  );
}
