import { useMutation, useQueryClient } from "@tanstack/react-query";

import { bodyApi, bodyKey, type Consents, type Scope } from "./bodyApi";
import { useConsents } from "./bodyHooks";

const SOURCES: Partial<Record<Scope, string>> = {
  "source:healthkit": "Lets Nexus import what Apple Health shares with it",
  "source:health_connect": "Lets Nexus import what Health Connect shares with it",
  "source:oauth": "Lets Nexus import from the apps and devices you connect",
  model_improvement: "Lets Nexus use your health logs to improve its models",
};

/** What each switch says it lets Nexus do. The AI one names who receives the logs, from the API. */
export function scopeLabel(scope: Scope, provider: Consents["ai_provider"]): string {
  if (scope === "ai_processing") return `Lets Nexus's AI provider (${provider.name}, ${provider.country}) read your health logs to answer you`;
  return SOURCES[scope] ?? scope;
}

/** One switch per consent scope in `/consents`. Turning one on or off is a request to the server, so the switch shows its answer. */
export function ConsentSwitches() {
  const client = useQueryClient();
  const consents = useConsents();
  const change = useMutation({
    mutationFn: ({ scope, on }: { scope: Scope; on: boolean }) => (on ? bodyApi.grant(scope) : bodyApi.withdraw(scope)),
    onSuccess: () => client.invalidateQueries({ queryKey: bodyKey.consents }),
  });
  if (consents.isError) return <p className="state error-text">Couldn't load your choices.</p>;
  if (!consents.data) return <p className="state">Loading…</p>;
  const { scopes, ai_provider: provider } = consents.data;
  return (
    <div className="health-stack" role="group" aria-label="What Nexus may do with your health data">
      {scopes.map((s) => {
        const label = scopeLabel(s.scope, provider);
        return (
          <label key={s.scope} className="share-switch">
            <input
              type="checkbox"
              role="switch"
              checked={s.active}
              disabled={change.isPending}
              aria-label={label}
              onChange={(e) => change.mutate({ scope: s.scope, on: e.target.checked })}
            />
            <span>{label}</span>
          </label>
        );
      })}
      {change.isError && (
        <p className="error-text" role="alert">
          {change.error instanceof Error ? change.error.message : "Couldn't save that"}
        </p>
      )}
    </div>
  );
}
