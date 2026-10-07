import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, useEffect, useId, useState } from "react";

import { api, type Direction, type MerchantSuggestion } from "../api";
import { formatMoney } from "../format";

/** The text after a short pause, so suggestions aren't fetched on every key. */
function useSettled(value: string, ms = 150): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

const detail = (s: MerchantSuggestion) =>
  [formatMoney(s.amount), s.category, s.times > 1 ? `${s.times} times` : null].filter(Boolean).join(" · ");

/** "Paid to" with suggestions from the user's own past entries: matches as they type,
 * and their most frequent ones as one-tap chips on a new entry. Picking one fills the
 * name, and the usual category and amount where they're still empty. */
export function MerchantField({
  label,
  value,
  direction,
  showFrequent,
  onChange,
  onPick,
}: {
  label: string;
  value: string;
  direction: Direction;
  showFrequent: boolean;
  onChange: (text: string) => void;
  onPick: (s: MerchantSuggestion) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const typed = useSettled(value.trim());
  const matches = useQuery({
    queryKey: ["merchant-suggestions", direction, typed],
    queryFn: () => api<MerchantSuggestion[]>(`/transactions/suggestions?direction=${direction}&q=${encodeURIComponent(typed)}`),
    enabled: typed.length > 0,
    staleTime: 60_000,
  });
  const frequent = useQuery({
    queryKey: ["merchant-suggestions", direction, ""],
    queryFn: () => api<MerchantSuggestion[]>(`/transactions/suggestions?direction=${direction}`),
    enabled: showFrequent,
    staleTime: 60_000,
  });
  const options = typed && typed === value.trim() ? (matches.data ?? []) : [];
  const shown = open && options.length > 0;

  function pick(s: MerchantSuggestion) {
    onPick(s);
    setOpen(false);
    setActive(-1);
  }

  function keys(e: KeyboardEvent<HTMLInputElement>) {
    if (!shown) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + options.length) % options.length);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pick(options[active]);
    } else if (e.key === "Escape") {
      e.stopPropagation(); // close the list, not the sheet
      setOpen(false);
    }
  }

  const chips = showFrequent && !value.trim() ? (frequent.data ?? []).slice(0, 4) : [];
  return (
    <div className="field merchant-field">
      <label htmlFor={`${id}-input`}>{label}</label>
      {chips.length > 0 && (
        <div className="chips merchant-chips" role="group" aria-label="Frequent">
          {chips.map((s) => (
            <button key={s.name} type="button" className="ask-chip" onClick={() => pick(s)} aria-label={`${s.name}, ${detail(s)}`}>
              {s.name} <span className="caption">{formatMoney(s.amount)}</span>
            </button>
          ))}
        </div>
      )}
      <input
        id={`${id}-input`}
        className="input"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={shown}
        aria-controls={`${id}-list`}
        aria-activedescendant={shown && active >= 0 ? `${id}-option-${active}` : undefined}
        autoComplete="off"
        maxLength={200}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={keys}
      />
      {shown && (
        <ul id={`${id}-list`} className="merchant-list" role="listbox" aria-label="Past merchants">
          {options.map((s, i) => (
            <li
              key={s.name}
              id={`${id}-option-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "is-active" : undefined}
              onMouseDown={(e) => e.preventDefault()} // keep focus, so blur doesn't close it first
              onClick={() => pick(s)}
            >
              <span>{s.name}</span>
              <span className="caption">{detail(s)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
