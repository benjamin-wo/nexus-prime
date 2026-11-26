import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, Suspense, useCallback, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { api, ApiError, type EditedTransaction, type Me, type RuleSuggestion, setCsrf, type Transaction } from "./api";
import { ChatDrawer } from "./components/ChatDrawer";
import { ErrorBoundary, pageFallback } from "./components/ErrorBoundary";
import { EntrySheet } from "./components/EntrySheet";
import { Shell } from "./components/Shell";
import { Toast } from "./components/Toast";
import { DEPARTMENTS } from "./departments";
import { EditTransactionProvider } from "./editTransaction";
import { nativeHaptic } from "./native";
import { isWaiting, outboxUser, useOnline, useOutbox, useOutboxSync } from "./outbox";
import { refetchActive, useRefreshOnReturn } from "./refreshOnReturn";
import { DemoPage } from "./pages/DemoPage";
import { Home } from "./pages/Home";
import { forgetTripNote, LoginPage } from "./pages/LoginPage";
import { lazyNamed } from "./lazyPage";
import { formatMoney, txName } from "./format";
import { initData, miniApp, tripInviteIn } from "./telegram";
import { useReportTimeZone } from "./timezone";

// Every page but Home and the sign-in page is fetched when its route is first opened.
const CashFlowPage = lazyNamed(() => import("./pages/CashFlow"), "CashFlowPage");
const ConnectDone = lazyNamed(() => import("./pages/Connect"), "ConnectDone");
const ConnectGmail = lazyNamed(() => import("./pages/Connect"), "ConnectGmail");
const Dashboard = lazyNamed(() => import("./pages/Dashboard"), "Dashboard");
const CostsPage = lazyNamed(() => import("./pages/Costs"), "CostsPage");
const EmailPage = lazyNamed(() => import("./pages/Email"), "EmailPage");
const HealthHome = lazyNamed(() => import("./health/HealthHome"), "HealthHome");
const HealthFood = lazyNamed(() => import("./health/HealthFood"), "HealthFood");
const HealthWeight = lazyNamed(() => import("./health/HealthWeight"), "HealthWeight");
const HealthGym = lazyNamed(() => import("./health/HealthGym"), "HealthGym");
const HealthToday = lazyNamed(() => import("./health/HealthToday"), "HealthToday");
const HealthRoutines = lazyNamed(() => import("./health/HealthRoutines"), "HealthRoutines");
const HealthLibrary = lazyNamed(() => import("./health/HealthLibrary"), "HealthLibrary");
const HealthHistory = lazyNamed(() => import("./health/HealthHistory"), "HealthHistory");
const InvestmentPage = lazyNamed(() => import("./pages/Investment"), "InvestmentPage");
const PlanPage = lazyNamed(() => import("./pages/Plans"), "PlanPage");
const PlansPage = lazyNamed(() => import("./pages/Plans"), "PlansPage");
const StockPage = lazyNamed(() => import("./pages/Stock"), "StockPage");
const ResearchPage = lazyNamed(() => import("./pages/Research"), "ResearchPage");
const SharedTripPage = lazyNamed(() => import("./pages/SharedTrip"), "SharedTripPage");
const TripPage = lazyNamed(() => import("./pages/Trips"), "TripPage");
const TripsPage = lazyNamed(() => import("./pages/Trips"), "TripsPage");
const WatchlistPage = lazyNamed(() => import("./pages/Watchlist"), "WatchlistPage");
const BudgetsPage = lazyNamed(() => import("./pages/BudgetsPage"), "BudgetsPage");
const NotificationsPage = lazyNamed(() => import("./pages/Notifications"), "NotificationsPage");
const ImportPage = lazyNamed(() => import("./pages/Import"), "ImportPage");
const NotFound = lazyNamed(() => import("./pages/NotFound"), "NotFound");
const Ledger = lazyNamed(() => import("./pages/Ledger"), "Ledger");
const Settings = lazyNamed(() => import("./pages/Settings"), "Settings");
const SettingsSection = lazyNamed(() => import("./pages/Settings"), "SettingsSection");
const TripInvite = lazyNamed(() => import("./pages/TripInvite"), "TripInvite");
const Upcoming = lazyNamed(() => import("./pages/Upcoming"), "Upcoming");
/** Dev only: every building block in each state. Vite folds import.meta.env.DEV to false in a production
 * build, so the import is dropped and the page never ships. */
const BlocksGallery = import.meta.env.DEV ? lazyNamed(() => import("./pages/BlocksGallery"), "BlocksGallery") : null;

const pageLoading = <p className="state">Loading…</p>;

/** The routed page, with its own error boundary: a page that crashes shows a notice in its place while
 * the rail, bottom bar and chat around it keep working, and going to another page tries again. */
function RoutedPage({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <ErrorBoundary resetKey={pathname} fallback={pageFallback}>
      <Suspense fallback={pageLoading}>{children}</Suspense>
    </ErrorBoundary>
  );
}

/** Inside Telegram, sign in with the Mini App's launch data instead of the widget. */
async function miniAppSignIn(): Promise<Me | null> {
  if (!initData) return null;
  try {
    // Opened from a trip's invite link: the server joins them to the trip as it signs them in.
    const tripInvite = tripInviteIn(window.location.pathname);
    return await api<Me>("/auth/webapp", {
      method: "POST",
      body: tripInvite ? { init_data: initData, trip_invite: tripInvite } : { init_data: initData },
    });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      miniApp.error = e.status === 403 ? "access" : "signin";
      return null;
    }
    throw e;
  }
}

function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      let me: Me | null;
      try {
        me = await api<Me>("/me");
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) throw e;
        me = await miniAppSignIn();
      }
      if (me) setCsrf(me.csrf_token);
      return me;
    },
    retry: false,
  });
}

/** A one-time line handed over by the page that sent us here (joining a trip says so), shown as a
 * Toast and then forgotten, so reloading the page doesn't say it again. */
function useRouteNotice(): [string | null, (notice: string | null) => void] {
  const location = useLocation();
  const navigate = useNavigate();
  const sent = (location.state as { notice?: string | null } | null)?.notice ?? null;
  const [notice, setNotice] = useState<string | null>(sent);
  useEffect(() => {
    if (location.state && "notice" in (location.state as object)) {
      navigate({ pathname: location.pathname, search: location.search, hash: location.hash }, { replace: true, state: null });
    }
  }, [location, navigate]);
  return [notice, setNotice];
}

/** Ends the session and sends everyone back to the sign-in page. */
function useLogout() {
  const client = useQueryClient();
  return async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    client.setQueryData(["me"], null);
  };
}

/** What a guest gets: the trips they are on and nothing else. No chat, no other department, no
 * Settings. The queries of the full app live in `Cockpit`, which a guest never mounts, so nothing
 * here asks the server for anything it refuses a guest. */
function GuestApp({ me }: { me: Me }) {
  const logout = useLogout();
  const [notice, setNotice] = useRouteNotice();
  const closeNotice = useCallback(() => setNotice(null), [setNotice]);
  return (
    <Shell me={me} onOpenChat={() => undefined} onLogout={logout}>
      <RoutedPage>
        <Routes>
          <Route path="/travel" element={<TripsPage />} />
          <Route path="/travel/trips/:id" element={<TripPage />} />
          <Route path="*" element={<Navigate to="/travel" replace />} />
        </Routes>
      </RoutedPage>
      {notice && <Toast message={notice} onClose={closeNotice} />}
    </Shell>
  );
}

function Cockpit({ me }: { me: Me }) {
  const client = useQueryClient();
  const logout = useLogout();
  // Tells Nexus where this browser is, once per page load, without holding anything up.
  useReportTimeZone(me.user);
  // The chat drawer, opened empty or with a question asked on Home.
  const [chat, setChat] = useState<{ ask?: string } | null>(null);
  const [sheet, setSheet] = useState<{ editing?: Transaction } | null>(null);
  // After a save: say so ("Logged SGD 5.50 · Kopi Stall", with Undo for a new entry), and after a
  // category correction offer a rule in the same line, changing nothing unless accepted.
  const [saved, setSaved] = useState<{ tx: EditedTransaction; fresh: boolean } | null>(null);
  // Also a line handed over by the page that sent us here (joining a trip says so).
  const [notice, setNotice] = useRouteNotice();
  // After deleting from the edit sheet: a line with Undo.
  const [deleted, setDeleted] = useState<{ tx: Transaction } | null>(null);
  const closeDeleted = useCallback(() => setDeleted(null), []);
  const closeSaved = useCallback(() => setSaved(null), []);
  const closeNotice = useCallback(() => setNotice(null), []);
  const refresh = useCallback(() => {
    for (const key of ["transactions", "summary", "ious", "budgets", "bills", "salary", "category-explanation", "email", "home", "runs", "investments", "watchlist", "stock", "plans", "plan", "wallets", "health"]) void client.invalidateQueries({ queryKey: [key] });
  }, [client]);
  // After a chat reply: the pages may have changed, and in the demo the messages left have.
  const changed = useCallback(() => {
    refresh();
    if (me.demo) void client.invalidateQueries({ queryKey: ["me"] });
  }, [client, refresh, me.demo]);
  const editTx = useCallback((tx: Transaction) => setSheet({ editing: tx }), []);
  const closeSheet = useCallback(() => setSheet(null), []);
  const closeChat = useCallback(() => setChat(null), []);
  // Ctrl/⌘ + K opens the chat from anywhere, empty: the way in on a keyboard, whichever page is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setChat((open) => open ?? {});
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  // Pulling a page down: what it shows, fetched again whatever its staleTime.
  const pullRefresh = useCallback(() => refetchActive(client, true), [client]);
  // Expenses logged with no connection are kept on the phone and sent when it can (outbox.ts).
  const outboxOwner = outboxUser(me);
  useOutboxSync(outboxOwner, client);
  const online = useOnline();
  const waiting = useOutbox(outboxOwner).filter(isWaiting).length;

  // Undo for an entry just logged: delete it (the server keeps it, so it can be restored), then refresh.
  const undoLogged = (tx: EditedTransaction) => ({
    label: "Undo",
    run: async () => {
      setSaved(null);
      try {
        await api(`/transactions/${tx.id}`, { method: "DELETE" });
        setNotice(txName(tx) === "No merchant" ? "Removed the entry." : `Removed ${txName(tx)}.`);
      } catch (e) {
        setNotice(e instanceof Error ? e.message : "Couldn't undo that");
      }
      refresh();
    },
  });

  return (
    <Shell
      me={me}
      onOpenChat={() => setChat({})}
      onLogout={logout}
      onRefresh={pullRefresh}
      offlineWaiting={online ? 0 : waiting}
    >
      <RoutedPage>
        <EditTransactionProvider onEdit={editTx}>
          <Routes>
            <Route path="/" element={<Navigate to="/app" replace />} />
            <Route path="/app" element={<Home me={me} onLog={() => setSheet({})} />} />
            <Route path="/accounting" element={<Dashboard me={me} onAsk={(ask) => setChat({ ask })} />} />
            <Route
              path="/accounting/ledger"
              element={<Ledger me={me} onAdd={() => setSheet({})} onEdit={(tx) => setSheet({ editing: tx })} />}
            />
            <Route path="/accounting/budgets" element={<BudgetsPage me={me} />} />
            <Route path="/accounting/cashflow" element={<CashFlowPage />} />
            <Route path="/investment" element={<InvestmentPage />} />
            <Route path="/investment/watchlist" element={<WatchlistPage />} />
            <Route path="/investment/stocks/:symbol" element={<StockPage />} />
            <Route path="/investment/plans" element={<PlansPage />} />
            <Route path="/investment/plans/:id" element={<PlanPage />} />
            <Route path="/travel" element={<TripsPage onAsk={(ask) => setChat({ ask })} />} />
            <Route path="/travel/trips/:id" element={<TripPage onAsk={(ask) => setChat({ ask })} />} />
            <Route path="/travel/research/:id" element={<ResearchPage />} />
            <Route path="/health" element={<HealthHome />} />
            <Route path="/health/food" element={<HealthFood />} />
            <Route path="/health/weight" element={<HealthWeight />} />
            <Route path="/health/gym" element={<HealthGym />}>
              <Route index element={<HealthToday />} />
              <Route path="routines" element={<HealthRoutines />} />
              <Route path="library" element={<HealthLibrary />} />
              <Route path="history" element={<HealthHistory />} />
            </Route>
            {/* Gym's pages used to sit straight under Health. */}
            <Route path="/health/routines" element={<Navigate to="/health/gym/routines" replace />} />
            <Route path="/health/library" element={<Navigate to="/health/gym/library" replace />} />
            <Route path="/health/history" element={<Navigate to="/health/gym/history" replace />} />
            {DEPARTMENTS.filter((d) => d.upcoming).map((d) => (
              <Route key={d.name} path={d.path} element={<Upcoming department={d} />} />
            ))}
            <Route path="/settings" element={<Settings me={me} onLogout={logout} />} />
            <Route path="/settings/email" element={<EmailPage me={me} />} />
            <Route path="/settings/import" element={<ImportPage />} />
            <Route path="/settings/costs" element={<CostsPage me={me} />} />
            <Route path="/settings/notifications" element={<NotificationsPage me={me} />} />
            {/* The rest of Settings, a section to a page: /settings/wallets, /settings/time-zone and so on. */}
            <Route path="/settings/:slug" element={<SettingsSection me={me} />} />
            {/* Where pages used to live, so old links and bookmarks still work. */}
            <Route path="/accounting/plan" element={<Navigate to="/accounting/budgets" replace />} />
            <Route path="/accounting/email" element={<Navigate to="/settings/email" replace />} />
            <Route path="/accounting/import" element={<Navigate to="/settings/import" replace />} />
            <Route path="/ledger" element={<Navigate to="/accounting/ledger" replace />} />
            <Route path="/cashflow" element={<Navigate to="/accounting/cashflow" replace />} />
            <Route path="/plan" element={<Navigate to="/accounting/budgets" replace />} />
            <Route path="/budgets" element={<Navigate to="/accounting/budgets" replace />} />
            <Route path="/email" element={<Navigate to="/settings/email" replace />} />
            <Route path="/import" element={<Navigate to="/settings/import" replace />} />
            {BlocksGallery && <Route path="/dev/blocks" element={<BlocksGallery />} />}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </EditTransactionProvider>
      </RoutedPage>
      {sheet && (
        <EntrySheet
          key={sheet.editing?.id ?? "new"}
          me={me}
          editing={sheet.editing}
          onOpen={(tx) => setSheet({ editing: tx })}
          onClose={closeSheet}
          onQueued={() => {
            setSheet(null);
            setNotice("Saved on this phone. It will sync when you're back online.");
          }}
          onDeleted={(tx) => {
            setSheet(null);
            refresh();
            setDeleted({ tx });
          }}
          onSaved={(tx: EditedTransaction) => {
            const fresh = !sheet.editing;
            setSheet(null);
            refresh();
            setNotice(null);
            setDeleted(null);
            setSaved({ tx, fresh });
            nativeHaptic("success");
          }}
        />
      )}
      {chat && <ChatDrawer ask={chat.ask} demo={me.demo} onClose={closeChat} onChanged={changed} />}
      {saved && (
        <Toast
          message={savedMessage(saved.tx, saved.fresh)}
          action={
            saved.tx.rule_suggestion
              ? {
                  label: saved.tx.rule_suggestion.replaces_category_id ? "Change rule" : "Save rule",
                  run: async () => {
                    const suggestion = saved.tx.rule_suggestion as RuleSuggestion;
                    setSaved(null);
                    try {
                      await api("/category-rules/accept", { method: "POST", body: { transaction_id: saved.tx.id } });
                      setNotice(`Saved. New expenses from “${suggestion.pattern}” will be filed the same way.`);
                      void client.invalidateQueries({ queryKey: ["category-rules"] });
                    } catch (e) {
                      setNotice(e instanceof Error ? e.message : "Couldn't save the rule");
                    }
                  },
                }
              : saved.fresh
                ? undoLogged(saved.tx)
                : undefined
          }
          also={saved.tx.rule_suggestion && saved.fresh ? undoLogged(saved.tx) : undefined}
          onClose={closeSaved}
        />
      )}
      {deleted && (
        <Toast
          message={`Deleted ${txName(deleted.tx)}.`}
          action={{
            label: "Undo",
            run: async () => {
              setDeleted(null);
              try {
                await api(`/transactions/${deleted.tx.id}/restore`, { method: "POST" });
                setNotice("Restored.");
              } catch (e) {
                setNotice(e instanceof Error ? e.message : "Couldn't restore");
              }
              refresh();
            },
          }}
          onClose={closeDeleted}
        />
      )}
      {notice && <Toast message={notice} onClose={closeNotice} />}
    </Shell>
  );
}

/** What the toast says after a save: "Logged SGD 5.50 · Kopi Stall" for a new entry, "Saved." for a
 * change, with a rule offer's question after it when there is one. */
export function savedMessage(tx: EditedTransaction, fresh: boolean): string {
  const name = txName(tx);
  const what = fresh ? `Logged ${[formatMoney(tx.amount), name === "No merchant" ? null : name].filter(Boolean).join(" · ")}` : "Saved";
  return `${what}.${tx.rule_suggestion ? ` ${tx.rule_suggestion.question}` : ""}`;
}

/** Where someone lands after signing in: a guest has Travel and nothing else, and a sign-in that
 * joined a trip opens it. */
function landing(me: Me): string {
  if (me.joined_trip) return `/travel/trips/${me.joined_trip}`;
  return me.user.role === "guest" ? "/travel" : "/app";
}

function Gate() {
  const me = useMe();
  useEffect(() => {
    // Signed in: a note left for the sign-in page about a trip invite is out of date.
    if (me.data) forgetTripNote();
  }, [me.data]);
  if (me.isLoading) return <p className="state">Loading…</p>;
  if (me.isError) return <p className="state error-text">Couldn't reach Nexus. Please reload.</p>;
  return (
    <Routes>
      {/* Opened from a one-time link, often without a session. */}
      <Route path="/connect/gmail" element={<ConnectGmail />} />
      <Route path="/connect/gmail/done" element={<ConnectDone />} />
      <Route path="/invite/:token" element={me.data ? <Navigate to={landing(me.data)} replace /> : <LoginPage />} />
      {/* A trip's invite link: signed in joins the trip; signed out signs in with the link, and the server joins them. */}
      <Route path="/trip-invite/:token" element={me.data ? <TripInvite me={me.data} /> : <LoginPage trip />} />
      {/* The resume's link: starts a demo account. Anyone already signed in just goes in. */}
      <Route path="/demo" element={me.data ? <Navigate to={landing(me.data)} replace /> : <DemoPage />} />
      <Route path="/login" element={me.data ? <Navigate to={landing(me.data)} replace /> : <LoginPage />} />
      <Route
        path="*"
        element={
          !me.data ? (
            <Navigate to="/login" replace />
          ) : me.data.user.role === "guest" ? (
            <GuestApp me={me.data} />
          ) : (
            <Cockpit me={me.data} />
          )
        }
      />
    </Routes>
  );
}

/** A request the server refused (403, 404, 422...) would be refused again: show it at once. Anything
 * else (a dropped connection, a 5xx) gets two more tries. */
export function retryQuery(failureCount: number, error: Error): boolean {
  return !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 2;
}

export function App({ client }: { client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: retryQuery } } }));
  // Telegram's WebView doesn't reliably give a window focus on return: refresh when the app is shown again.
  useRefreshOnReturn(queryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <Suspense fallback={pageLoading}>
            <Routes>
              {/* A trip's read-only link: opened by anyone, so it never waits on a sign-in. */}
              <Route path="/shared/:token" element={<SharedTripPage />} />
              <Route path="*" element={<Gate />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
