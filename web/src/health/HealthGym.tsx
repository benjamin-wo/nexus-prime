import { Outlet } from "react-router-dom";

import { Tabs } from "../components/ui";

const ITEMS = [
  { to: "/health/gym", label: "Workout", end: true },
  { to: "/health/gym/routines", label: "Routines" },
  { to: "/health/gym/library", label: "Library" },
  { to: "/health/gym/history", label: "History" },
];

/** Gym: its own pages under one tab of Health. Each page keeps its own heading. */
export function HealthGym() {
  return (
    <>
      <Tabs label="Gym pages" items={ITEMS} />
      <Outlet />
    </>
  );
}
