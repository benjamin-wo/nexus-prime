import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import type { Me } from "../api";
import { DEPARTMENTS, departmentFor } from "../departments";
import { useReveal } from "../motion";
import { Icon, departmentIcon } from "./Icon";
import { withMiniApp } from "../telegram";
import { InviteButton } from "./InviteButton";

/** True while the page is being scrolled down (past its top, short of its end):
 * the floating buttons step aside then, so they never sit on what's being read,
 * and come back on the way up or at the end of the page. */
function useScrollingDown(area: RefObject<HTMLElement | null>, page: string): boolean {
  const [down, setDown] = useState(false);
  useEffect(() => {
    const el = area.current;
    setDown(false);
    if (!el) return;
    let last = el.scrollTop;
    const onScroll = () => {
      const top = el.scrollTop;
      const atEnd = top + el.clientHeight >= el.scrollHeight - 24;
      if (atEnd || top < 80 || top < last - 6) setDown(false);
      else if (top > last + 6) setDown(true);
      if (Math.abs(top - last) > 6 || atEnd) last = top;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [area, page]);
  return down;
}

/** A page inside a section (a trip, a stock, a plan) and where "back" goes when
 * there's no earlier page to return to. */
const DETAIL: [RegExp, string][] = [
  [/^\/travel\/(trips|research)\/./, "/travel"],
  [/^\/investment\/stocks\/./, "/investment/watchlist"],
  [/^\/investment\/plans\/./, "/investment/plans"],
  [/^\/accounting\/import/, "/accounting/ledger"],
];

/** In Telegram, its own back button (top left) on a page inside a section. */
function useTelegramBack(pathname: string, first: boolean) {
  const navigate = useNavigate();
  const parent = DETAIL.find(([pattern]) => pattern.test(pathname))?.[1];
  useEffect(() => {
    let undo = () => {};
    const stop = withMiniApp((app) => {
      const back = app.BackButton;
      if (!back) return;
      if (!parent) {
        back.hide();
        return;
      }
      const go = () => (first ? navigate(parent) : navigate(-1));
      back.onClick(go);
      back.show();
      undo = () => back.offClick(go);
    });
    return () => {
      stop();
      undo();
    };
  }, [parent, first, navigate]);
}

/** Telegram's header (and the bar under the app) in the page's own colour: the
 * hero's orange on Home, the page colour elsewhere. */
const SHELL_BG = "#f4f1ec";
const HERO_TOP = "#e4570f";
const BAR_BG = "#12100e";
function useTelegramColours(home: boolean) {
  useEffect(
    () =>
      withMiniApp((app) => {
        app.setHeaderColor?.(home ? HERO_TOP : SHELL_BG);
        app.setBackgroundColor?.(SHELL_BG);
        app.setBottomBarColor?.(BAR_BG);
      }),
    [home],
  );
}

/** The front desk (Home), a switcher for the departments behind it, Settings and
 * Nexus: a rail on wide screens; on phones a dark bottom bar with Nexus in the
 * middle. A department's own pages are tabs along the top of its section. */
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
  const { pathname, key } = useLocation();
  useTelegramBack(pathname, key === "default");
  useTelegramColours(pathname === "/");
  const here = departmentFor(pathname);
  const content = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLElement>(null);
  const scrolling = useScrollingDown(viewport, pathname);
  useReveal(content);
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
    <NavLink to="/settings" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      <span className="nav-glyph" aria-hidden="true">
        <Icon name="settings" />
      </span>
      <span className="nav-label">Settings</span>
    </NavLink>
  );
  const nexus = (where: string) => (
    <button type="button" className={`nexus-button ${where}`} aria-label="Ask Nexus" title="Ask Nexus" onClick={onOpenChat}>
      <Icon name="sparkle" size={22} />
      {where === "in-rail" && <span>Ask Nexus</span>}
    </button>
  );
  return (
    <div className={`shell${scrolling ? " scrolling-down" : ""}`}>
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
        {nexus("in-rail")}
        <div className="spacer" />
        {me.user.role === "owner" && <InviteButton />}
        <button type="button" className="btn btn-ghost" onClick={onLogout}>
          Sign out
        </button>
      </nav>
      <main className="main-viewport" ref={viewport}>
        <div className="content" ref={content}>
          {/* One tab is no choice: only show the bar when there are two or more. */}
          {here && here.tabs.length > 1 && (
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
      {/* Home and Accounting, Nexus in the middle, then Investment and Travel. Settings
          is on Home (top right). */}
      <nav className="bottom-nav" aria-label="Main (mobile)">
        {links.slice(0, 2)}
        {nexus("in-bar")}
        {links.slice(2)}
      </nav>
    </div>
  );
}
