import { useId } from "react";

/** What of a TanStack query a Retry needs: to fetch again, and whether that is under way. */
type Retryable = { refetch: () => unknown; isFetching?: boolean };

/** A failed load, said in words with a Retry that fetches it again: "Couldn't load your trips."
 * Shown in place of what the query would have held, never beside copy that reads as an empty
 * answer ("No spending recorded", "Nothing needs you"). `block` sits inside a card that is already
 * there; `page` is a card of its own, for a list or page with no card around it. */
export function LoadError({
  message,
  query,
  variant = "block",
}: {
  message: string;
  query: Retryable;
  variant?: "block" | "page";
}) {
  const id = useId();
  return (
    <div className={`load-error${variant === "page" ? " load-error-page" : ""}`} role="alert">
      <p id={id} className="error-text load-error-text">
        {message}
      </p>
      <button type="button" className="btn btn-small" aria-describedby={id} disabled={query.isFetching} onClick={() => void query.refetch()}>
        Retry
      </button>
    </div>
  );
}
