import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Category } from "../api";

function CategoryRow({
  category,
  others,
  onChanged,
}: {
  category: Category;
  others: Category[];
  onChanged: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(category.name);
  const [confirming, setConfirming] = useState(false);
  const [merging, setMerging] = useState(false);
  const [into, setInto] = useState("");
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

  async function merge(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/categories/${category.id}/merge`, { method: "POST", body: { into_id: into } });
      setMerging(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't merge");
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault();
    void patch({ name: name.trim() });
  }

  return (
    <li className="budget">
      {merging ? (
        <form className="quick" onSubmit={merge} aria-label={`Merge ${category.name}`}>
          <label className="field">
            Move everything in {category.name} into
            <select className="input" value={into} onChange={(e) => setInto(e.target.value)} required>
              <option value="">Pick a category</option>
              {others.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <p className="caption">Its expenses, rules and budget move over, and {category.name} is archived.</p>
          <button type="submit" className="btn btn-primary" disabled={!into}>
            Merge
          </button>
          <button type="button" className="btn" onClick={() => setMerging(false)}>
            Cancel
          </button>
        </form>
      ) : renaming ? (
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
                  <button type="button" className="btn btn-ghost" onClick={() => setMerging(true)}>
                    Merge into…
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

/** The user's categories: the 12 defaults and their own. Every expense lands in one. */
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
            <CategoryRow key={c.id} category={c} others={active.filter((o) => o.id !== c.id)} onChanged={refresh} />
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
              <CategoryRow key={c.id} category={c} others={[]} onChanged={refresh} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
