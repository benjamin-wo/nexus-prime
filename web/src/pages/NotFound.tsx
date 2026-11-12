import { Link } from "react-router-dom";

/** Where an address that matches no page lands, instead of silently being sent Home. */
export function NotFound() {
  return (
    <section className="not-found" aria-labelledby="not-found-title">
      <h1 id="not-found-title">This page doesn't exist</h1>
      <p className="muted">It may have moved, or the link is old.</p>
      <Link className="btn btn-primary" to="/">
        Back to Home
      </Link>
    </section>
  );
}
