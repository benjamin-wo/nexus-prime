import { Link, Outlet, useLocation } from "react-router-dom";

import { Tabs } from "../components/ui";

const ITEMS = [
  { to: "/health/gym", label: "Workout", end: true },
  { to: "/health/gym/routines", label: "Routines" },
  { to: "/health/gym/library", label: "Library" },
  { to: "/health/gym/history", label: "History" },
];

/** Gym: the workout is the main view. Routines, Library and History sit behind one More link, and show their own tabs. */
export function HealthGym() {
  const main = /^\/health\/gym\/?$/.test(useLocation().pathname);
  return (
    <>
      {!main && <Tabs label="Gym pages" items={ITEMS} />}
      <Outlet />
      {main && (
        <p className="health-actions">
          <Link to="/health/gym/routines">More: routines, library, history</Link>
        </p>
      )}
    </>
  );
}
