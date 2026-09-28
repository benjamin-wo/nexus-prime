import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { api, ApiError, type Me, setCsrf, type Transaction } from "./api";
import { ChatDrawer } from "./components/ChatDrawer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { EntrySheet } from "./components/EntrySheet";
import { Shell } from "./components/Shell";
import { Dashboard } from "./pages/Dashboard";
import { Ledger } from "./pages/Ledger";
import { LoginPage } from "./pages/LoginPage";
import { Plan } from "./pages/Plan";
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
  const [chat, setChat] = useState(false);
  const [sheet, setSheet] = useState<{ editing?: Transaction } | null>(null);
  const refresh = useCallback(() => {
    for (const key of ["transactions", "summary", "ious", "budgets", "bills"]) void client.invalidateQueries({ queryKey: [key] });
  }, [client]);
  const closeSheet = useCallback(() => setSheet(null), []);
  const closeChat = useCallback(() => setChat(false), []);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    client.setQueryData(["me"], null);
  }

  return (
    <Shell me={me} onOpenChat={() => setChat(true)} onLogout={logout}>
      <Routes>
        <Route
          path="/"
          element={<Dashboard me={me} onLog={() => setSheet({})} onOpenChat={() => setChat(true)} />}
        />
        <Route
          path="/ledger"
          element={<Ledger me={me} onAdd={() => setSheet({})} onEdit={(tx) => setSheet({ editing: tx })} />}
        />
        <Route path="/plan" element={<Plan me={me} />} />
        <Route path="/budgets" element={<Navigate to="/plan" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {sheet && (
        <EntrySheet
          me={me}
          editing={sheet.editing}
          onClose={closeSheet}
          onSaved={() => {
            setSheet(null);
            refresh();
          }}
        />
      )}
      {chat && <ChatDrawer onClose={closeChat} onChanged={refresh} />}
    </Shell>
  );
}

function Gate() {
  const me = useMe();
  if (me.isLoading) return <p className="state">Loading…</p>;
  if (me.isError) return <p className="state error-text">Couldn't reach Nexus. Please reload.</p>;
  return (
    <Routes>
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
