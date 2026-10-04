import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, type ImportLayout, type ImportPreview, type ImportRecord, type ImportRow } from "../api";
import { formatDate, formatMoney } from "../format";

const MAX_CSV_BYTES = 2_000_000;
const MAX_PDF_BYTES = 10_000_000;

type PdfRead = {
  needs_password: boolean;
  wrong_password: boolean;
  csv: string | null;
  layout: ImportLayout | null;
  kind: "card" | "account" | null;
  rows: number;
  reconciles: boolean | null;
};

async function base64Of(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
const VERDICT: Record<ImportRow["verdict"], { label: string; className: string }> = {
  new: { label: "New", className: "badge badge-in" },
  duplicate: { label: "Possible duplicate", className: "badge badge-pending" },
  imported: { label: "Already imported", className: "badge badge-deleted" },
  unclear: { label: "Can't read", className: "badge badge-deleted" },
};

function ColumnSelect({
  label,
  headers,
  value,
  onChange,
  optional = false,
}: {
  label: string;
  headers: string[];
  value: number | null;
  onChange: (value: number | null) => void;
  optional?: boolean;
}) {
  return (
    <label className="field">
      {label}
      <select
        className="input"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      >
        {optional && <option value="">None</option>}
        {headers.map((h, i) => (
          <option key={i} value={i}>
            {h || `Column ${i + 1}`}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Which column holds what. Changing anything previews again. */
function LayoutEditor({
  headers,
  layout,
  onChange,
}: {
  headers: string[];
  layout: ImportLayout;
  onChange: (layout: ImportLayout) => void;
}) {
  const split = layout.amount === null;
  const set = (patch: Partial<ImportLayout>) => onChange({ ...layout, ...patch });
  return (
    <div className="import-layout" aria-label="Columns">
      <ColumnSelect label="Date" headers={headers} value={layout.date} onChange={(v) => set({ date: v ?? 0 })} />
      <ColumnSelect
        label="Description"
        headers={headers}
        value={layout.description[0] ?? 0}
        onChange={(v) => set({ description: [v ?? 0, ...layout.description.slice(1, 2)] })}
      />
      <ColumnSelect
        label="More description"
        headers={headers}
        optional
        value={layout.description[1] ?? null}
        onChange={(v) => set({ description: v === null ? [layout.description[0]] : [layout.description[0], v] })}
      />
      <label className="field">
        Amounts
        <select
          className="input"
          value={split ? "split" : "one"}
          onChange={(e) =>
            e.target.value === "split"
              ? set({ amount: null, debit: layout.amount ?? 0, credit: layout.amount ?? 0 })
              : set({ amount: layout.debit ?? layout.credit ?? 0, debit: null, credit: null })
          }
        >
          <option value="one">One column</option>
          <option value="split">Money out and in apart</option>
        </select>
      </label>
      {split ? (
        <>
          <ColumnSelect label="Money out" headers={headers} optional value={layout.debit} onChange={(v) => set({ debit: v })} />
          <ColumnSelect label="Money in" headers={headers} optional value={layout.credit} onChange={(v) => set({ credit: v })} />
        </>
      ) : (
        <>
          <ColumnSelect label="Amount" headers={headers} value={layout.amount} onChange={(v) => set({ amount: v ?? 0 })} />
          <label className="field">
            Spending shows as
            <select
              className="input"
              value={layout.sign}
              onChange={(e) => set({ sign: e.target.value as ImportLayout["sign"] })}
            >
              <option value="negative_is_out">Negative (-12.30)</option>
              <option value="positive_is_out">Positive (a card statement)</option>
            </select>
          </label>
        </>
      )}
      <label className="field">
        Dates are
        <select
          className="input"
          value={layout.date_order}
          onChange={(e) => set({ date_order: e.target.value as ImportLayout["date_order"] })}
        >
          <option value="dmy">Day first (28/09)</option>
          <option value="mdy">Month first (09/28)</option>
          <option value="ymd">Year first (2026-09-28)</option>
        </select>
      </label>
      <ColumnSelect label="Currency" headers={headers} optional value={layout.currency} onChange={(v) => set({ currency: v })} />
    </div>
  );
}

function RowLine({ row, checked, onToggle }: { row: ImportRow; checked: boolean; onToggle: () => void }) {
  const verdict = VERDICT[row.verdict];
  const selectable = row.verdict === "new" || row.verdict === "duplicate";
  return (
    <tr>
      <td className="select">
        <input
          type="checkbox"
          aria-label={`Import ${row.description || `row ${row.index + 1}`}`}
          checked={checked}
          disabled={!selectable}
          onChange={onToggle}
        />
      </td>
      <td className="date">{row.date ? formatDate(`${row.date}T12:00:00`) : row.cells.join(" · ").slice(0, 30)}</td>
      <td className="merchant wrap">
        {row.description || "—"}
        {row.matches && (
          <span className="caption fx">
            Looks like {formatDate(`${row.matches.date}T12:00:00`)} {row.matches.description ?? ""}{" "}
            {row.matches.amount}
          </span>
        )}
        {row.problem && <span className="caption fx">{row.problem}</span>}
      </td>
      <td className="hide-mobile">{row.category ?? ""}</td>
      <td className={`amount ${row.direction === "in" ? "amount-in" : "amount-out"}`}>
        {row.amount && row.currency
          ? `${row.direction === "in" ? "+" : "−"}${formatMoney({ amount: row.amount, currency: row.currency })}`
          : ""}
      </td>
      <td className="status">
        <span className={verdict.className}>{verdict.label}</span>
      </td>
    </tr>
  );
}

/** Import a bank statement: pick a CSV, check the preview, import the ticked rows. */
export function ImportPage() {
  const client = useQueryClient();
  const history = useQuery({ queryKey: ["imports"], queryFn: () => api<ImportRecord[]>("/imports") });
  const [file, setFile] = useState<{ name: string; text: string; fromPdf: boolean } | null>(null);
  const [locked, setLocked] = useState<{ name: string; pdf: string; wrong: boolean } | null>(null);
  const [password, setPassword] = useState("");
  const [check, setCheck] = useState<boolean | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [saveAs, setSaveAs] = useState("");
  const [save, setSave] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ImportRecord | null>(null);

  async function show(text: string, layout: ImportLayout | null) {
    setBusy(true);
    setError(null);
    try {
      const shown = await api<ImportPreview>("/imports/preview", { method: "POST", body: { csv: text, layout } });
      setPreview(shown);
      setTicked(new Set(shown.rows.filter((r) => r.verdict === "new").map((r) => r.index)));
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : "Couldn't read that file");
    } finally {
      setBusy(false);
    }
  }

  async function openPdf(name: string, pdf: string, pass: string | null) {
    setBusy(true);
    setError(null);
    try {
      const read = await api<PdfRead>("/imports/pdf", { method: "POST", body: { pdf, password: pass } });
      if (read.needs_password || !read.csv || !read.layout) {
        setLocked({ name, pdf, wrong: read.wrong_password });
        setBusy(false);
        return;
      }
      setLocked(null);
      setPassword("");
      setCheck(read.reconciles);
      setFile({ name, text: read.csv, fromPdf: true });
      await show(read.csv, read.layout);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't read that PDF");
      setBusy(false);
    }
  }

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0];
    setDone(null);
    setPreview(null);
    setLocked(null);
    setCheck(null);
    if (!picked) return;
    const isPdf = picked.type === "application/pdf" || picked.name.toLowerCase().endsWith(".pdf");
    if (picked.size > (isPdf ? MAX_PDF_BYTES : MAX_CSV_BYTES)) {
      setError(isPdf ? "That PDF is larger than 10 MB." : "That file is larger than 2 MB.");
      return;
    }
    if (isPdf) {
      await openPdf(picked.name, await base64Of(picked), null);
      return;
    }
    const text = await picked.text();
    setFile({ name: picked.name, text, fromPdf: false });
    await show(text, null);
  }

  async function confirm() {
    if (!file || !preview?.layout) return;
    setBusy(true);
    setError(null);
    try {
      const record = await api<ImportRecord>("/imports", {
        method: "POST",
        body: {
          csv: file.text,
          layout: preview.layout,
          include: [...ticked],
          file_name: file.name,
          save_as: save && saveAs.trim() && !file.fromPdf ? saveAs.trim() : null,
        },
      });
      setDone(record);
      setPreview(null);
      setFile(null);
      void client.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't import");
    } finally {
      setBusy(false);
    }
  }

  async function undo(record: ImportRecord) {
    await api(`/imports/${record.id}/undo`, { method: "POST" });
    if (done?.id === record.id) setDone(null);
    void client.invalidateQueries();
  }

  const counts = (verdict: ImportRow["verdict"]) => preview?.rows.filter((r) => r.verdict === verdict).length ?? 0;
  const toggle = (index: number) =>
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Import a statement</h1>
          <p className="muted">
            A CSV or PDF statement from your bank or card. Nothing is added until you check it and confirm.
          </p>
        </div>
        <Link className="btn" to="/accounting/ledger">
          Back to ledger
        </Link>
      </div>

      <section className="card" aria-labelledby="import-file">
        <h2 id="import-file">Statement file</h2>
        <label className="field">
          Choose a CSV or PDF
          <input
            className="input"
            type="file"
            accept=".csv,.pdf,text/csv,application/pdf"
            onChange={choose}
            disabled={busy}
          />
        </label>
        {locked && (
          <form
            className="import-actions"
            onSubmit={(e) => {
              e.preventDefault();
              void openPdf(locked.name, locked.pdf, password);
            }}
          >
            <label className="field">
              {locked.wrong ? "That password didn't open it. Try again" : "This PDF is locked. Its password"}
              <input
                className="input"
                type="password"
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={!password || busy}>
              Open
            </button>
            <span className="caption">Used only to read this file; it isn't kept.</span>
          </form>
        )}
        {busy && <p className="state">Reading…</p>}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {done && (
          <div className="quick" role="status">
            <span>
              Imported {done.added} transaction{done.added === 1 ? "" : "s"}
              {done.skipped ? `; ${done.skipped} left out` : ""}.
            </span>
            <button type="button" className="btn" onClick={() => undo(done)}>
              Undo import
            </button>
            <Link className="btn btn-ghost" to="/accounting/ledger">
              See the ledger
            </Link>
          </div>
        )}
      </section>

      {preview && file && (
        <section className="card" aria-labelledby="import-preview">
          <div className="card-head">
            <h2 id="import-preview">Check before importing</h2>
            <span className="caption">
              {preview.saved_as ? `Using your saved layout “${preview.saved_as}”` : file.name}
            </span>
          </div>
          {file.fromPdf ? (
            <p className={check === false ? "error-text" : "caption"} role="note">
              {check === true && "Read from the PDF. These rows add up to the statement's own totals."}
              {check === false &&
                "Read from the PDF, but these rows don't add up to the statement's totals: some may be missing. Check them against the statement."}
              {check === null && "Read from the PDF. The statement doesn't state totals to check against."}
            </p>
          ) : preview.layout ? (
            <LayoutEditor headers={preview.headers} layout={preview.layout} onChange={(l) => show(file.text, l)} />
          ) : (
            <>
              <p className="state">I couldn't tell which columns hold the date, description and amount. Pick them:</p>
              <LayoutEditor
                headers={preview.headers}
                layout={{ date: 0, description: [1], amount: 2, debit: null, credit: null, currency: null, date_order: "dmy", sign: "negative_is_out" }}
                onChange={(l) => show(file.text, l)}
              />
            </>
          )}
          {preview.rows.length > 0 && (
            <>
              <p className="caption">
                {counts("new")} new · {counts("duplicate")} possible duplicates (left unticked) ·{" "}
                {counts("imported")} already imported · {counts("unclear")} can't be read
              </p>
              <div className="table-wrap">
                <table className="ledger import-table">
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="date-caption">Import</span>
                      </th>
                      <th scope="col">Date</th>
                      <th scope="col">Description</th>
                      <th scope="col" className="hide-mobile">
                        Category
                      </th>
                      <th scope="col" className="amount">
                        Amount
                      </th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row) => (
                      <RowLine key={row.index} row={row} checked={ticked.has(row.index)} onToggle={() => toggle(row.index)} />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="import-actions">
                {!file.fromPdf && (
                  <>
                    <label className="check">
                      <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} /> Remember
                      these columns as
                    </label>
                    <input
                      className="input"
                      placeholder="My bank"
                      aria-label="Name for this layout"
                      value={saveAs}
                      onChange={(e) => setSaveAs(e.target.value)}
                      disabled={!save}
                    />
                  </>
                )}
                <button type="button" className="btn btn-primary" onClick={confirm} disabled={busy || ticked.size === 0}>
                  Import {ticked.size} transaction{ticked.size === 1 ? "" : "s"}
                </button>
              </div>
            </>
          )}
        </section>
      )}

      <section className="card" aria-labelledby="import-history">
        <h2 id="import-history">Past imports</h2>
        {history.data?.length === 0 && <p className="state">No imports yet.</p>}
        {history.data && history.data.length > 0 && (
          <ul className="memory-list">
            {history.data.map((r) => (
              <li key={r.id} className="memory-row">
                <span className="wrap">
                  {r.file_name} · {r.added} added · {formatDate(r.created_at)}
                  {r.undone_at && <span className="caption"> · undone</span>}
                </span>
                {!r.undone_at && (
                  <button type="button" className="btn btn-ghost" onClick={() => undo(r)}>
                    Undo
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
