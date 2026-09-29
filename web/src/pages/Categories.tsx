import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Category } from "../api";

function CategoryRow({ category, onChanged }: { category: Category; onChanged: () => void }) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(category.name);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function patch(body: { name?: string; active?: boolean }) {
    setError(null);
    try {
      await api(`/categories/${category.id}`, { method: "PATCH", body });
      setRenaming(false);
      setConfirming(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault();
    void patch({ name: name.trim() });
  }

  return (
    <li className="budget">
      {renaming ? (
        <form className="quick" onSubmit={rename} aria-label={`Rename ${category.name}`}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
          <button type="submit" className="btn btn-primary" disabled={!name.trim()}>
            Save
          </button>
          <button type="button" className="btn" onClick={() => setRenaming(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <div className="budget-head">
          <h3 className={`wrap${category.active ? "" : " muted"}`}>{category.name}</h3>
          <span className="quick">
            {category.active ? (
              confirming ? (
                <>
                  <span>Stop using it?</span>
                  <button type="button" className="btn btn-danger" onClick={() => patch({ active: false })}>
                    Archive
                  </button>
                  <button type="button" className="btn" onClick={() => setConfirming(false)}>
                    Keep
                  </button>
                </>
              ) : (
                <>
                  <button type="button" className="btn btn-ghost" onClick={() => setRenaming(true)}>
                    Rename
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
                    Archive
                  </button>
                </>
              )
            ) : (
              <button type="button" className="btn btn-ghost" onClick={() => patch({ active: true })}>
                Bring back
              </button>
            )}
          </span>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** The user's categories: the 11 defaults and their own. Every expense lands in one. */
export function CategoriesSection() {
  const client = useQueryClient();
  const all = useQuery({
    queryKey: ["categories", "all"],
    queryFn: () => api<Category[]>("/categories?include_inactive=true"),
  });
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    void client.invalidateQueries({ queryKey: ["categories"] });
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/categories", { method: "POST", body: { name: name.trim() } });
      setName("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add it");
    }
  }

  const active = all.data?.filter((c) => c.active) ?? [];
  const archived = all.data?.filter((c) => !c.active) ?? [];
  return (
    <section className="card" aria-labelledby="categories">
      <div className="card-head">
        <h2 id="categories">Categories</h2>
        <span className="caption">Every expense lands in one</span>
      </div>
      {all.isLoading && <p className="state">Loading…</p>}
      {all.isError && <p className="state error-text">Couldn't load categories.</p>}
      {active.length > 0 && (
        <ul className="budgets" aria-label="Your categories">
          {active.map((c) => (
            <CategoryRow key={c.id} category={c} onChanged={refresh} />
          ))}
        </ul>
      )}
      <form className="budget-add plan-add" onSubmit={add} aria-label="Add a category">
        <label className="field">
          New category
          <input className="input" placeholder="Pets" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <button type="submit" className="btn btn-primary" disabled={!name.trim()}>
          Add
        </button>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </form>
      {archived.length > 0 && (
        <>
          <h3 className="caption">Archived (past expenses keep them)</h3>
          <ul className="budgets" aria-label="Archived categories">
            {archived.map((c) => (
              <CategoryRow key={c.id} category={c} onChanged={refresh} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
