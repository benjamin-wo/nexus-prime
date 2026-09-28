import type { Transaction } from "../api";

export function DirectionBadge({ tx }: { tx: Transaction }) {
  if (tx.deleted) return <span className="badge badge-deleted">Deleted</span>;
  if (tx.status === "pending") return <span className="badge badge-pending">Pending</span>;
  return tx.direction === "out" ? (
    <span className="badge badge-out">Money out</span>
  ) : (
    <span className="badge badge-in">Money in</span>
  );
}
