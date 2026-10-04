import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

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
import { ImportPage } from "./pages/Import";
import { Ledger } from "./pages/Ledger";
import { LoginPage } from "./pages/LoginPage";
import { Plan } from "./pages/Plan";
import { Settings } from "./pages/Settings";
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

function Cockpit({ me }: { me: Me }) {
  const client = useQueryClient();
  // The chat drawer, opened empty or with a question asked on Home.
  const [chat, setChat] = useState<{ ask?: string } | null>(null);
  const [sheet, setSheet] = useState<{ editing?: Transaction } | null>(null);
  // After a category correction: offer a rule, and change nothing unless accepted.
  const [offer, setOffer] = useState<{ transactionId: string; suggestion: RuleSuggestion } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const closeOffer = useCallback(() => setOffer(null), []);
  const closeNotice = useCallback(() => setNotice(null), []);
  const refresh = useCallback(() => {
    for (const key of ["transactions", "summary", "ious", "budgets", "bills", "salary", "category-explanation", "email", "home", "runs"]) void client.invalidateQueries({ queryKey: [key] });
  }, [client]);
  const closeSheet = useCallback(() => setSheet(null), []);
  const closeChat = useCallback(() => setChat(null), []);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    client.setQueryData(["me"], null);
  }

  return (
    <Shell me={me} onOpenChat={() => setChat({})} onLogout={logout}>
      <Routes>
        <Route path="/" element={<Home me={me} onAsk={(ask) => setChat({ ask })} />} />
        <Route path="/accounting" element={<Dashboard me={me} onLog={() => setSheet({})} />} />
        <Route
          path="/accounting/ledger"
          element={<Ledger me={me} onAdd={() => setSheet({})} onEdit={(tx) => setSheet({ editing: tx })} />}
        />
        <Route path="/accounting/plan" element={<Plan me={me} />} />
        <Route path="/accounting/cashflow" element={<CashFlowPage />} />
        <Route path="/accounting/email" element={<EmailPage me={me} />} />
        <Route path="/accounting/import" element={<ImportPage />} />
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

function Gate() {
  const me = useMe();
  if (me.isLoading) return <p className="state">Loading…</p>;
  if (me.isError) return <p className="state error-text">Couldn't reach Nexus. Please reload.</p>;
  return (
    <Routes>
      {/* Opened from a one-time link, often without a session. */}
      <Route path="/connect/gmail" element={<ConnectGmail />} />
      <Route path="/connect/gmail/done" element={<ConnectDone />} />
      <Route path="/invite/:token" element={me.data ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/login" element={me.data ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="*" element={me.data ? <Cockpit me={me.data} /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}

export function App({ client }: { client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? new QueryClient({ defaultOptions: { queries: { staleTime: 15_000 } } }));
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <Gate />
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
