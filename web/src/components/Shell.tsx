import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";

import type { Me } from "../api";
import { DEPARTMENTS, departmentFor, inMenu } from "../departments";
import { useReveal } from "../motion";
import { DemoBanner } from "./DemoBanner";
import { Icon, departmentIcon } from "./Icon";
import { pullIsSafe, withMiniApp } from "../telegram";
import { CHROME, useScheme } from "../theme";
import { type PullStatus, usePullToRefresh } from "../usePullToRefresh";
import { InviteButton } from "./InviteButton";
import { NexusMark } from "./NexusMark";

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

/** The bottom bar's height (its safe-area padding too), kept in --bar-h on the shell so the page's
 * bottom padding always clears the bar, whatever the text size or the device's inset. */
function useBarHeight(shell: RefObject<HTMLElement | null>, bar: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = shell.current;
    const el = bar.current;
    if (!root || !el) return;
    const measure = () => root.style.setProperty("--bar-h", `${el.offsetHeight}px`);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const watcher = new ResizeObserver(measure);
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [shell, bar]);
}

/** A page inside a section (a trip, a stock, a plan) and where "back" goes when
 * there's no earlier page to return to. */
const DETAIL: [RegExp, string][] = [
  [/^\/travel\/(trips|research)\/./, "/travel"],
  [/^\/investment\/stocks\/./, "/investment/watchlist"],
  [/^\/investment\/plans\/./, "/investment/plans"],
  [/^\/settings\/./, "/settings"],
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
 * hero's indigo on Home, the page colour elsewhere. */
function useTelegramColours(home: boolean) {
  const scheme = useScheme();
  useEffect(
    () =>
      withMiniApp((app) => {
        const colours = CHROME[scheme];
        app.setHeaderColor?.(home ? colours.hero : colours.shell);
        app.setBackgroundColor?.(colours.shell);
        app.setBottomBarColor?.(colours.bar);
      }),
    [home, scheme],
  );
}

/** The pages of money data that can be pulled down to refresh: Home, the Money overview, the Ledger and Budgets. */
const PULLABLE = new Set(["/", "/accounting", "/accounting/ledger", "/accounting/budgets"]);

/** The spinner that shows while a page is pulled down and refreshed, announced as "Refreshing…" and
 * "Updated". The button is for keyboards and screen readers (it shows only while focused). */
function PullIndicator({ status, onRefresh }: { status: PullStatus; onRefresh?: () => void }) {
  return (
    <div className={`ptr ptr-${status}`}>
      <div className="ptr-spinner" aria-hidden="true" />
      <p className="sr-only" role="status">
        {status === "refreshing" ? "Refreshing…" : status === "done" ? "Updated" : ""}
      </p>
      {onRefresh && (
        <button type="button" className="btn btn-soft ptr-button" onClick={onRefresh}>
          Refresh
        </button>
      )}
    </div>
  );
}

/** The brand mark, as the rail and a guest's header show it. */
function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <NexusMark size={34} />
    </span>
  );
}

/** The front desk (Home), a switcher for the departments behind it, Settings and
 * Kaya: a rail on wide screens; on phones a dark bottom bar with Kaya in the
 * middle. A department's own pages are tabs along the top of its section.
 *
 * A guest (someone a trip's owner brought in) gets none of that: a slim header with
 * the app's name and Sign out above their trips, and no chat. */
export function Shell({
  me,
  onOpenChat,
  onLogout,
  onRefresh,
  offlineWaiting = 0,
  children,
}: {
  me: Me;
  onOpenChat: () => void;
  onLogout: () => void;
  /** Refetches what the page shows; given, Home, Money overview, Ledger and Budgets can be pulled down to refresh. */
  onRefresh?: () => Promise<unknown>;
  /** While the phone is offline: how many expenses saved on it are waiting to sync. A notice shows above the page. */
  offlineWaiting?: number;
  children: ReactNode;
}) {
  const { pathname, key } = useLocation();
  useTelegramBack(pathname, key === "default");
  useTelegramColours(pathname === "/");
  const here = departmentFor(pathname);
  const content = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLElement>(null);
  const scrolling = useScrollingDown(viewport, pathname);
  const shell = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLElement>(null);
  useBarHeight(shell, bar);
  useReveal(content);
  const pullable = onRefresh && PULLABLE.has(pathname) ? onRefresh : undefined;
  const pull = usePullToRefresh(viewport, pullable, pullIsSafe);
  // The rail names each place in full; the bottom bar on a phone uses a short word under the icon,
  // and its accessible name keeps the full one ("Invest (Investment)").
  const links = (bar: boolean) => [
    <NavLink key="home" to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      <span className="nav-glyph" aria-hidden="true">
        <Icon name="home" />
      </span>
      <span className="nav-label">Home</span>
    </NavLink>,
    ...DEPARTMENTS.filter((d) => inMenu(d, me.preferences)).map((d) => (
      <NavLink
        key={d.name}
        to={d.path}
        className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
        aria-label={bar && d.short !== d.label ? `${d.short} (${d.label})` : undefined}
      >
        <span className="nav-glyph" aria-hidden="true">
          <Icon name={departmentIcon(d.name)} />
        </span>
        <span className="nav-label">{bar ? d.short : d.label}</span>
      </NavLink>
    )),
  ];
  const barLinks = links(true);
  const settings = (
    <NavLink to="/settings" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      <span className="nav-glyph" aria-hidden="true">
        <Icon name="settings" />
      </span>
      <span className="nav-label">Settings</span>
    </NavLink>
  );
  if (me.user.role === "guest") {
    return (
      <div className={`shell guest-shell${scrolling ? " scrolling-down" : ""}`}>
        <header className="guest-bar">
          <Link className="guest-brand" to="/travel">
            <BrandMark />
            <span>Kaya</span>
          </Link>
          <div className="guest-user">
            {me.user.display_name && <span className="guest-name">{me.user.display_name}</span>}
            <button type="button" className="btn btn-ghost" onClick={onLogout}>
              Sign out
            </button>
          </div>
        </header>
        <main className="main-viewport" ref={viewport}>
          <div className="content" ref={content}>
            {children}
          </div>
        </main>
      </div>
    );
  }
  const nexus = (where: string) => (
    <button type="button" className={`nexus-button ${where}`} aria-label="Ask Kaya" title="Ask Kaya" onClick={onOpenChat}>
      <NexusMark size={where === "in-rail" ? 28 : 38} variant="mono" />
      {where === "in-rail" && <span>Ask Kaya</span>}
    </button>
  );
  return (
    <div className={`shell${scrolling ? " scrolling-down" : ""}`} ref={shell}>
      {me.demo && <DemoBanner expiresAt={me.demo.expires_at} onSignIn={onLogout} />}
      {offlineWaiting > 0 && (
        <div className="offline-notice" role="status">
          <p>
            You're offline. {offlineWaiting} {offlineWaiting === 1 ? "expense" : "expenses"} will sync when you're
            back.
          </p>
        </div>
      )}
      <nav className="rail" aria-label="Main">
        <div className="brand">
          <BrandMark />
          <span>Kaya</span>
        </div>
        {links(false)}
        {settings}
        {nexus("in-rail")}
        <div className="spacer" />
        {me.user.role === "owner" && !me.demo && <InviteButton />}
        <button type="button" className="btn btn-ghost" onClick={onLogout}>
          Sign out
        </button>
      </nav>
      <main className="main-viewport" ref={viewport}>
        {pullable && <PullIndicator status={pull.status} onRefresh={pull.refresh} />}
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
      {/* Home and Money, Kaya in the middle, then Invest and Travel when they are in the menu,
          each with a short label under its icon. The places are split over two equal halves, so
          Kaya stays in the middle with three, four or five items. Settings is on Home (top
          right). */}
      <nav className="bottom-nav" aria-label="Main (mobile)" ref={bar}>
        <div className="bar-side">{barLinks.slice(0, Math.ceil(barLinks.length / 2))}</div>
        {nexus("in-bar")}
        <div className="bar-side">{barLinks.slice(Math.ceil(barLinks.length / 2))}</div>
      </nav>
    </div>
  );
}
