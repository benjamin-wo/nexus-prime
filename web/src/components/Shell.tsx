import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import type { Me } from "../api";
import { InviteButton } from "./InviteButton";

const links = [
  { to: "/", label: "Dashboard" },
  { to: "/ledger", label: "Ledger" },
  { to: "/plan", label: "Plan" },
  { to: "/cashflow", label: "Cash flow" },
];

export function Shell({
  me,
  onOpenChat,
  onLogout,
  children,
}: {
  me: Me;
  onOpenChat: () => void;
  onLogout: () => void;
  children: ReactNode;
}) {
  const nav = links.map((link) => (
    <NavLink key={link.to} to={link.to} end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      {link.label}
    </NavLink>
  ));
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">
          Nexus <span>Prime</span>
        </div>
        {nav}
        <button type="button" className="btn btn-ghost" onClick={onOpenChat}>
          Open chat
        </button>
        <div className="spacer" />
        {me.user.role === "owner" && <InviteButton />}
        <button type="button" className="btn btn-ghost" onClick={onLogout}>
          Sign out
        </button>
      </nav>
      <main className="main-viewport">
        <div className="content">{children}</div>
      </main>
      <nav className="bottom-nav" aria-label="Main (mobile)">
        {nav}
        <button type="button" className="btn btn-ghost" onClick={onOpenChat}>
          Chat
        </button>
      </nav>
    </div>
  );
}
