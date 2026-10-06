import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

import type { Me } from "../api";
import { DEPARTMENTS, departmentFor } from "../departments";
import { Icon, departmentIcon } from "./Icon";
import { InviteButton } from "./InviteButton";

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

/** The front desk (Home), a switcher for the departments behind it, and Settings:
 * a rail on wide screens and a bottom bar on phones. A department's own pages are
 * tabs along the top of its section. */
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
  const here = departmentFor(useLocation().pathname);
  const links = [
    <NavLink key="home" to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      <span className="nav-glyph" aria-hidden="true">
        <Icon name="home" />
      </span>
      <span className="nav-label">Home</span>
    </NavLink>,
    ...DEPARTMENTS.map((d) => (
      <NavLink key={d.name} to={d.path} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
        <span className="nav-glyph" aria-hidden="true">
          <Icon name={departmentIcon(d.name)} />
        </span>
        <span className="nav-label">{d.label}</span>
      </NavLink>
    )),
  ];
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
          <span className="brand-mark" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
              strokeLinecap="round" strokeLinejoin="round" focusable="false">
              <path d="M5 19V5l14 14V5" />
            </svg>
          </span>
          <span>
            Nexus <span className="brand-accent">Prime</span>
          </span>
        </div>
        {links}
        {settings}
        <div className="spacer" />
        {me.user.role === "owner" && <InviteButton />}
        <button type="button" className="btn btn-ghost" onClick={onLogout}>
          Sign out
        </button>
      </nav>
      <main className="main-viewport">
        <div className="content">
          {here && here.tabs.length > 0 && (
            <nav className="dept-tabs" aria-label={`${here.label} pages`}>
              {here.tabs.map((tab) => (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) => `dept-tab${isActive ? " active" : ""}`}
                >
                  {tab.label}
                </NavLink>
              ))}
            </nav>
          )}
          {children}
        </div>
      </main>
      <nav className="bottom-nav" aria-label="Main (mobile)">
        {links}
        {settings}
      </nav>
      {/* Chat floats over every page, clear of the tabs. */}
      <button type="button" className="chat-fab" aria-label="Open chat" title="Chat" onClick={onOpenChat}>
        <ChatIcon />
      </button>
    </div>
  );
}
