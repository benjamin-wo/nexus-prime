/** Keeps the page steady when a phone's keyboard opens.
 *
 * The keyboard shrinks the visible screen. Anything sized to the screen would stretch
 * and redraw, and anything pinned to its bottom (the tab bar and the add button)
 * would jump up onto the keyboard. So:
 *
 * - `--stable-height` holds the screen's height without the keyboard: set on load,
 *   on rotation, and on any resize that isn't the keyboard opening.
 * - `html.keyboard` is set while a text field has focus on a touch screen; the bar
 *   and the floating buttons hide until it closes.
 * - `--vv-height` and `--vv-top` hold the visible screen (what the keyboard leaves,
 *   and where the browser has panned to) so the chat can fit above the keyboard
 *   instead of sitting partly under it. */

const NOT_TYPED = new Set(["checkbox", "radio", "button", "submit", "reset", "file", "range", "color", "image"]);

export function typesText(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el instanceof HTMLInputElement) return !NOT_TYPED.has(el.type) && !el.readOnly;
  return el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement || el.isContentEditable;
}

export function watchViewport(win: Window = window): () => void {
  const doc = win.document;
  const root = doc.documentElement;
  const touch = () => win.matchMedia?.("(pointer: coarse)").matches === true;
  let width = win.innerWidth;
  let closing = 0;

  const remember = () => root.style.setProperty("--stable-height", `${win.innerHeight}px`);
  const onResize = () => {
    // A new width is a rotation or a resized window; the same width while typing is
    // the keyboard, which mustn't change the stable height.
    if (win.innerWidth !== width || !root.classList.contains("keyboard")) {
      width = win.innerWidth;
      remember();
    }
  };
  const onFocusIn = (e: FocusEvent) => {
    if (!touch() || !typesText(e.target as Element)) return;
    win.clearTimeout(closing);
    root.classList.add("keyboard");
  };
  const onFocusOut = () => {
    // Moving from one field to the next shouldn't flash the bar in between.
    win.clearTimeout(closing);
    closing = win.setTimeout(() => {
      if (!typesText(doc.activeElement)) root.classList.remove("keyboard");
    }, 150);
  };

  // The visual viewport is what is left above the keyboard; `innerHeight` and a fixed
  // `bottom: 0` still count the keyboard on iOS.
  const vv = win.visualViewport;
  const follow = () => {
    if (!vv) return;
    root.style.setProperty("--vv-height", `${vv.height}px`);
    root.style.setProperty("--vv-top", `${vv.offsetTop}px`);
  };

  remember();
  follow();
  win.addEventListener("resize", onResize);
  vv?.addEventListener("resize", follow);
  vv?.addEventListener("scroll", follow);
  doc.addEventListener("focusin", onFocusIn);
  doc.addEventListener("focusout", onFocusOut);
  return () => {
    win.clearTimeout(closing);
    win.removeEventListener("resize", onResize);
    vv?.removeEventListener("resize", follow);
    vv?.removeEventListener("scroll", follow);
    root.style.removeProperty("--vv-height");
    root.style.removeProperty("--vv-top");
    doc.removeEventListener("focusin", onFocusIn);
    doc.removeEventListener("focusout", onFocusOut);
    root.classList.remove("keyboard");
  };
}
