import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Icon } from "./Icon";

/** One line in a menu: a page (`to`), a file or address (`href`), or an action (`onSelect`). */
export type MenuItem = {
  key: string;
  label: string;
  to?: string;
  href?: string;
  download?: boolean;
  onSelect?: () => void;
};

/** A button that opens a short list of actions ("More"). It is a menu button: the button
 * says whether it is open, the first item takes focus on opening, the arrow keys move
 * between items, and Escape, Tab, a pick or a press outside closes it. */
export function Menu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    box.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  function key(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const all = [...(box.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
      const at = all.indexOf(document.activeElement as HTMLElement);
      const next =
        e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : e.key === "ArrowDown" ? (at + 1) % all.length : (at <= 0 ? all.length : at) - 1;
      all[next]?.focus();
    }
  }

  const pick = (item: MenuItem) => {
    setOpen(false);
    item.onSelect?.();
  };

  return (
    <div className="menu" ref={box} onKeyDown={key}>
      <button
        ref={button}
        type="button"
        className="btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen(!open)}
      >
        {label}
        <Icon name="chevronDown" size={16} />
      </button>
      {open && (
        <div id={listId} className="menu-list" role="menu" aria-label={label}>
          {items.map((item) =>
            item.to ? (
              <Link key={item.key} className="menu-item" role="menuitem" to={item.to} onClick={() => pick(item)}>
                {item.label}
              </Link>
            ) : item.href ? (
              <a key={item.key} className="menu-item" role="menuitem" href={item.href} download={item.download} onClick={() => pick(item)}>
                {item.label}
              </a>
            ) : (
              <button key={item.key} type="button" className="menu-item" role="menuitem" onClick={() => pick(item)}>
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
