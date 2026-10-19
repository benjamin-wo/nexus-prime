import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { acceptInvitePath, api, ApiError, type JoinedTrip, type Me, type Trip } from "../api";

type Opened = { tripId: string; notice: string | null };

/** Joins the trip the link is for. A trip already on is just opened, with nothing said. */
async function join(token: string): Promise<Opened> {
  const joined = await api<JoinedTrip>(acceptInvitePath(token), { method: "POST" });
  // Their own link: nothing is joined, so the trip just opens, with a word on what the link is for.
  if (joined.own) return { tripId: joined.trip_id, notice: "That's your own invite link. Send it to the person you want on the trip." };
  if (!joined.new) return { tripId: joined.trip_id, notice: null };
  // The name is only for the notice, so not finding it never stops them joining.
  let notice = "You've joined the trip.";
  try {
    const trip = (await api<Trip[]>("/travel/trips")).find((t) => t.id === joined.trip_id);
    if (trip) notice = `You've joined the trip to ${trip.destination}.`;
  } catch {
    // keep the plain notice
  }
  return { tripId: joined.trip_id, notice };
}

/** `/trip-invite/:token` for someone signed in: join the trip, then open it. (Signed out, the
 * sign-in page carries the link instead, and the server joins them as they sign in.) */
export function TripInvite({ me }: { me: Me }) {
  const { token = "" } = useParams();
  const client = useQueryClient();
  // A query, not an effect: a link works once, so it must be sent once, and the answer is kept
  // for as long as the page is open (pressing Back here must not spend the link again).
  const opened = useQuery({
    queryKey: ["trip-invite", token],
    queryFn: () => join(token),
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const tripId = opened.data?.tripId;
  useEffect(() => {
    if (tripId) void client.invalidateQueries({ queryKey: ["trips"] });
  }, [tripId, client]);

  if (opened.data) {
    return <Navigate to={`/travel/trips/${opened.data.tripId}`} replace state={{ notice: opened.data.notice }} />;
  }
  const guest = me.user.role === "guest";
  const where = guest ? { to: "/travel", label: "Go to Trips" } : { to: "/", label: "Go to Home" };

  if (opened.isError) {
    const status = opened.error instanceof ApiError ? opened.error.status : 0;
    if (status === 404 || status === 410) {
      return (
        <div className="login">
          <section className="card">
            <h1>This invite doesn't work any more</h1>
            <p className="secondary">Ask the trip's owner for a new link.</p>
            <Link className="btn btn-primary" to={where.to}>
              {where.label}
            </Link>
          </section>
        </div>
      );
    }
    return (
      <div className="login">
        <section className="card">
          <h1>Couldn't join the trip</h1>
          <p className="error-text" role="alert">
            {opened.error instanceof Error && opened.error.message ? opened.error.message : "Something went wrong."}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => void opened.refetch()}>
            Try again
          </button>
        </section>
      </div>
    );
  }
  return (
    <div className="login">
      <section className="card">
        <p className="state" role="status">
          Joining the trip…
        </p>
      </section>
    </div>
  );
}
