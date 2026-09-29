import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Category, type CategoryRule } from "../api";

function RuleRow({ rule, onChanged }: { rule: CategoryRule; onChanged: () => void }) {
  const [confirming, setConfirming] = useState(false);

  async function remove() {
    await api(`/category-rules/${rule.id}`, { method: "DELETE" });
    onChanged();
  }

  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">“{rule.pattern}”</h3>
        <span>→ {rule.category_name}</span>
      </div>
      <div className="budget-foot">
        <span className="caption">{rule.explanation}</span>
        {confirming ? (
          <span className="quick">
            <span>Remove this rule?</span>
            <button type="button" className="btn btn-danger" onClick={remove}>
              Remove
            </button>
            <button type="button" className="btn" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </span>
        ) : (
          <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
            Remove
          </button>
        )}
      </div>
    </li>
  );
}

/** Category rules: each one says why it exists, and only changes when the user does it. */
export function RulesSection() {
  const client = useQueryClient();
  const rules = useQuery({ queryKey: ["category-rules"], queryFn: () => api<CategoryRule[]>("/category-rules") });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const [pattern, setPattern] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const chosen = categoryId || categories.data?.[0]?.id || "";

  function refresh() {
    void client.invalidateQueries({ queryKey: ["category-rules"] });
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/category-rules", { method: "PUT", body: { pattern: pattern.trim(), category_id: chosen } });
      setPattern("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  return (
    <section className="card" aria-labelledby="rules">
      <div className="card-head">
        <h2 id="rules">Category rules</h2>
        <span className="caption">File new expenses by merchant or notes</span>
      </div>
      {rules.isLoading && <p className="state">Loading…</p>}
      {rules.isError && <p className="state error-text">Couldn't load rules.</p>}
      {rules.data?.length === 0 && (
        <p className="state">No rules yet. Add one below, or change an expense's category and I'll offer one.</p>
      )}
      {rules.data && rules.data.length > 0 && (
        <ul className="budgets">
          {rules.data.map((r) => (
            <RuleRow key={r.id} rule={r} onChanged={refresh} />
          ))}
        </ul>
      )}
      <form className="budget-add plan-add" onSubmit={add} aria-label="Add a rule">
        <label className="field">
          When it mentions
          <input
            className="input"
            placeholder="grab"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            required
          />
        </label>
        <label className="field">
          File under
          <select className="input" value={chosen} onChange={(e) => setCategoryId(e.target.value)}>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn btn-primary" disabled={!pattern.trim() || !chosen}>
          Save rule
        </button>
        <p className="caption">Existing expenses stay as they are; a rule only files new ones.</p>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
