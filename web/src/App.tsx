import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { api, ApiError, type EditedTransaction, type Me, type RuleSuggestion, setCsrf, type Transaction } from "./api";
import { ChatDrawer } from "./components/ChatDrawer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { EntrySheet } from "./components/EntrySheet";
import { Shell } from "./components/Shell";
import { Toast } from "./components/Toast";
import { CashFlowPage } from "./pages/CashFlow";
import { ConnectDone, ConnectGmail } from "./pages/Connect";
import { DEPARTMENTS } from "./departments";
import { Dashboard } from "./pages/Dashboard";
import { EmailPage } from "./pages/Email";
import { Home } from "./pages/Home";
import { InvestmentPage } from "./pages/Investment";
import { PlanPage, PlansPage } from "./pages/Plans";
import { StockPage } from "./pages/Stock";
import { ResearchPage } from "./pages/Research";
import { SharedTripPage } from "./pages/SharedTrip";
import { TripPage, TripsPage } from "./pages/Trips";
import { WatchlistPage } from "./pages/Watchlist";
import { ImportPage } from "./pages/Import";
import { Ledger } from "./pages/Ledger";
import { forgetTripNote, LoginPage } from "./pages/LoginPage";
import { Plan } from "./pages/Plan";
import { Settings } from "./pages/Settings";
import { TripInvite } from "./pages/TripInvite";
import { Upcoming } from "./pages/Upcoming";
import { initData, miniApp } from "./telegram";

/** Inside Telegram, sign in with the Mini App's launch data instead of the widget. */
async function miniAppSignIn(): Promise<Me | null> {
  if (!initData) return null;
  try {
    return await api<Me>("/auth/webapp", { method: "POST", body: { init_data: initData } });
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
      <Routes>
        <Route path="/travel" element={<TripsPage />} />
        <Route path="/travel/trips/:id" element={<TripPage />} />
        <Route path="*" element={<Navigate to="/travel" replace />} />
      </Routes>
      {notice && <Toast message={notice} onClose={closeNotice} />}
    </Shell>
  );
}

function Cockpit({ me }: { me: Me }) {
  const client = useQueryClient();
  const logout = useLogout();
  // The chat drawer, opened empty or with a question asked on Home.
  const [chat, setChat] = useState<{ ask?: string } | null>(null);
  const [sheet, setSheet] = useState<{ editing?: Transaction } | null>(null);
  // After a category correction: offer a rule, and change nothing unless accepted.
  const [offer, setOffer] = useState<{ transactionId: string; suggestion: RuleSuggestion } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const closeOffer = useCallback(() => setOffer(null), []);
  const closeNotice = useCallback(() => setNotice(null), []);
  const refresh = useCallback(() => {
    for (const key of ["transactions", "summary", "ious", "budgets", "bills", "salary", "category-explanation", "email", "home", "runs", "investments", "watchlist", "stock", "plans", "plan"]) void client.invalidateQueries({ queryKey: [key] });
  }, [client]);
  const closeSheet = useCallback(() => setSheet(null), []);
  const closeChat = useCallback(() => setChat(null), []);

  return (
    <Shell me={me} onOpenChat={() => setChat({})} onLogout={logout}>
      <Routes>
        <Route path="/" element={<Home me={me} onAsk={(ask) => setChat({ ask })} onLog={() => setSheet({})} />} />
        <Route path="/accounting" element={<Dashboard me={me} onLog={() => setSheet({})} onAsk={(ask) => setChat({ ask })} />} />
        <Route
          path="/accounting/ledger"
          element={<Ledger me={me} onAdd={() => setSheet({})} onEdit={(tx) => setSheet({ editing: tx })} />}
        />
        <Route path="/accounting/plan" element={<Plan me={me} />} />
        <Route path="/accounting/cashflow" element={<CashFlowPage />} />
        <Route path="/accounting/email" element={<EmailPage me={me} />} />
        <Route path="/accounting/import" element={<ImportPage />} />
        <Route path="/investment" element={<InvestmentPage />} />
        <Route path="/investment/watchlist" element={<WatchlistPage />} />
        <Route path="/investment/stocks/:symbol" element={<StockPage />} />
        <Route path="/investment/plans" element={<PlansPage />} />
        <Route path="/investment/plans/:id" element={<PlanPage />} />
        <Route path="/travel" element={<TripsPage onAsk={(ask) => setChat({ ask })} />} />
        <Route path="/travel/trips/:id" element={<TripPage onAsk={(ask) => setChat({ ask })} />} />
        <Route path="/travel/research/:id" element={<ResearchPage />} />
        {DEPARTMENTS.filter((d) => d.upcoming).map((d) => (
          <Route key={d.name} path={d.path} element={<Upcoming department={d} />} />
        ))}
        <Route path="/settings" element={<Settings />} />
        {/* Where pages used to live, so old links and bookmarks still work. */}
        {["ledger", "plan", "cashflow", "email", "import"].map((page) => (
          <Route key={page} path={`/${page}`} element={<Navigate to={`/accounting/${page}`} replace />} />
        ))}
        <Route path="/budgets" element={<Navigate to="/accounting/plan" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {sheet && (
        <EntrySheet
          key={sheet.editing?.id ?? "new"}
          me={me}
          editing={sheet.editing}
          onOpen={(tx) => setSheet({ editing: tx })}
          onClose={closeSheet}
          onSaved={(tx: EditedTransaction) => {
            setSheet(null);
            refresh();
            if (tx.rule_suggestion) setOffer({ transactionId: tx.id, suggestion: tx.rule_suggestion });
          }}
        />
      )}
      {chat && <ChatDrawer ask={chat.ask} onClose={closeChat} onChanged={refresh} />}
      {offer && (
        <Toast
          message={offer.suggestion.question}
          action={{
            label: offer.suggestion.replaces_category_id ? "Change rule" : "Save rule",
            run: async () => {
              setOffer(null);
              try {
                await api("/category-rules/accept", { method: "POST", body: { transaction_id: offer.transactionId } });
                setNotice(`Saved. New expenses from “${offer.suggestion.pattern}” will be filed the same way.`);
                void client.invalidateQueries({ queryKey: ["category-rules"] });
              } catch (e) {
                setNotice(e instanceof Error ? e.message : "Couldn't save the rule");
              }
            },
          }}
          onClose={closeOffer}
        />
      )}
      {notice && <Toast message={notice} onClose={closeNotice} />}
    </Shell>
  );
}

/** Where someone lands after signing in: a guest has Travel and nothing else, and a sign-in that
 * joined a trip opens it. */
function landing(me: Me): string {
  if (me.joined_trip) return `/travel/trips/${me.joined_trip}`;
  return me.user.role === "guest" ? "/travel" : "/";
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

export function App({ client }: { client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? new QueryClient({ defaultOptions: { queries: { staleTime: 15_000 } } }));
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            {/* A trip's read-only link: opened by anyone, so it never waits on a sign-in. */}
            <Route path="/shared/:token" element={<SharedTripPage />} />
            <Route path="*" element={<Gate />} />
          </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
