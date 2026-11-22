import { ButtonLink } from "../components/ui";

import "./settings.css";

/** Where an address that matches no page lands, instead of silently being sent Home. */
export function NotFound() {
  return (
    <section className="not-found" aria-labelledby="not-found-title">
      <h1 id="not-found-title">This page doesn't exist</h1>
      <p className="muted">It may have moved, or the link is old.</p>
      <ButtonLink variant="primary" to="/app">
        Back to Home
      </ButtonLink>
    </section>
  );
}
