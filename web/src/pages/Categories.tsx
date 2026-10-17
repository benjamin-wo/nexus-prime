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
  const [moveTo, setMoveTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  const keepsForever = ["other", "income"].includes(category.name.toLowerCase());
  const fallback = others.find((c) => c.name.toLowerCase() === "other")?.id ?? "";
  const target = others.some((c) => c.id === moveTo) ? moveTo : fallback;

  async function patch(body: { name: string }) {
    setError(null);
    try {
      await api(`/categories/${category.id}`, { method: "PATCH", body });
      setRenaming(false);
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

  async function remove() {
    setError(null);
    try {
      await api(`/categories/${category.id}?move_to=${encodeURIComponent(target)}`, { method: "DELETE" });
      setConfirming(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete");
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
          <p className="caption">Its expenses, rules and budget move over, and {category.name} is deleted.</p>
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
          <h3 className="wrap">{category.name}</h3>
          <span className="quick">
            {confirming ? (
              <>
                <span>Delete {category.name}? Its expenses move to</span>
                <select
                  className="input"
                  aria-label={`Move ${category.name} expenses to`}
                  value={target}
                  onChange={(e) => setMoveTo(e.target.value)}
                >
                  {others.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <button type="button" className="btn btn-danger" disabled={!target} onClick={() => void remove()}>
                  Delete
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
                {!keepsForever && (
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
                    Delete
                  </button>
                )}
              </>
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
    queryFn: () => api<Category[]>("/categories"),
  });
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  function refresh() {
    for (const key of ["categories", "transactions", "budgets", "category-rules"])
      void client.invalidateQueries({ queryKey: [key] });
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

  const categories = all.data ?? [];
  return (
    <section className="card" aria-labelledby="categories">
      <div className="card-head">
        <h2 id="categories">Categories</h2>
        <span className="caption">Every expense lands in one</span>
      </div>
      {all.isLoading && <p className="state">Loading…</p>}
      {all.isError && <p className="state error-text">Couldn't load categories.</p>}
      {!open && categories.length > 0 && (
        <>
          <p className="caption">
            {categories.length} {categories.length === 1 ? "category" : "categories"}
          </p>
          <ul className="chips category-chips" aria-label="Category names">
            {categories.map((c) => (
              <li key={c.id} className="chip">
                {c.name}
              </li>
            ))}
          </ul>
        </>
      )}
      <details className="category-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="btn">{open ? "Done" : "Manage"}</summary>
        {categories.length > 0 && (
          <ul className="budgets" aria-label="Your categories">
            {categories.map((c) => (
              <CategoryRow key={c.id} category={c} others={categories.filter((o) => o.id !== c.id)} onChanged={refresh} />
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
      </details>
    </section>
  );
}
