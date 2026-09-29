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

function CogIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.8 8.8 0 0 1-3.9-.9L3 20.5l1.5-4.6A8.1 8.1 0 0 1 3.5 11.5 8.5 8.5 0 0 1 12 3a8.5 8.5 0 0 1 9 8.5z" />
    </svg>
  );
}

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
  const settings = (
    <NavLink
      to="/settings"
      aria-label="Settings"
      title="Settings"
      className={({ isActive }) => `nav-link nav-icon${isActive ? " active" : ""}`}
    >
      <CogIcon />
    </NavLink>
  );
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">
          Nexus <span>Prime</span>
        </div>
        {nav}
        {settings}
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
        {settings}
      </nav>
      {/* Chat floats over every page, clear of the tabs. */}
      <button type="button" className="chat-fab" aria-label="Open chat" title="Chat" onClick={onOpenChat}>
        <ChatIcon />
      </button>
    </div>
  );
}
