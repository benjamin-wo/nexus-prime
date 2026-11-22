// @vitest-environment node
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * Guards DESIGN.md's token-only rule in styles.css and the stylesheets split out of it (overlay.css).
 *
 * - Colour literals (hex, rgb(), rgba(), hsl(), hsla()) live only in `:root` blocks (the light tokens, the dark
 *   tokens under prefers-color-scheme and under data-theme). Everywhere else a colour is a `var(--token)`.
 *   `rgba(var(--accent-rgb), 0.16)` is fine: the colour is still a token.
 * - No linear-gradient / radial-gradient / conic-gradient, anywhere.
 * - A box-shadow is `none` or built only from `var(--shadow-*)` tokens: no coloured or glow shadows.
 * - font-family is `inherit`, a `var(--font-*)` token, or one of the stacks named in DESIGN.md.
 *
 * styles.css still breaks these rules in places the token and component PRs have not reached. Each one is
 * listed in KNOWN_OFFENDERS as "selector :: kind". The test fails on a violation that is not listed, and also
 * on a listed offender that no longer exists, so the list can only shrink. KNOWN_OFFENDERS MUST ONLY SHRINK:
 * never add to it to make a new rule pass, fix the rule; when you fix one, delete its line.
 */

type Kind = "colour" | "gradient" | "shadow" | "font";

const SRC = dirname(fileURLToPath(import.meta.url));
const CSS_PATH = join(SRC, "styles.css");
/** Split-out stylesheets are held to the same rules (styles.css is being split up, overlay.css first). */
const OTHER_CSS = [join(SRC, "components/overlay/overlay.css")];

const FONT_STACKS = [
  // Paper: Bricolage Grotesque (headings, figures, UI) and Newsreader (body), plus mono.
  '"Bricolage Grotesque", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  '"Newsreader", Georgia, "Times New Roman", serif',
  "ui-monospace, SFMono-Regular, Menlo, monospace",
];

const COLOUR_LITERAL = /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?)\((?!\s*var\()/i;
const GRADIENT = /\b(?:linear|radial|conic)-gradient\(/i;

interface Decl { selector: string; prop: string; value: string }

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** A small CSS reader: every declaration with the selector it sits under (media blocks are looked through). */
function readDeclarations(css: string): Decl[] {
  const out: Decl[] = [];
  interface Block { kind: "group" | "rule" | "keyframes" | "skip"; selector: string }
  const stack: Block[] = [];
  let buf = "";
  let paren = 0;
  let quote = "";

  const owner = (): Block | undefined => {
    for (let i = stack.length - 1; i >= 0; i--) if (stack[i].kind !== "group") return stack[i];
    return undefined;
  };
  const flush = () => {
    const text = buf.trim();
    buf = "";
    const b = owner();
    if (!text || !b || b.kind === "skip") return;
    const at = text.indexOf(":");
    if (at < 0) return;
    out.push({ selector: b.selector, prop: text.slice(0, at).trim().toLowerCase(), value: text.slice(at + 1).trim() });
  };

  for (const ch of stripComments(css)) {
    if (quote) {
      buf += ch;
      if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; buf += ch; continue; }
    if (ch === "(") paren++;
    if (ch === ")") paren--;
    if (ch === "{" && paren === 0) {
      const prelude = buf.replace(/\s+/g, " ").trim();
      buf = "";
      const parent = owner();
      if (parent?.kind === "keyframes" || parent?.kind === "skip") {
        stack.push({ kind: parent.kind, selector: parent.selector }); // a keyframe step: same owner
      } else if (prelude.startsWith("@font-face")) {
        stack.push({ kind: "skip", selector: prelude });
      } else if (/^@(?:-\w+-)?keyframes/.test(prelude)) {
        stack.push({ kind: "keyframes", selector: prelude });
      } else if (prelude.startsWith("@")) {
        stack.push({ kind: "group", selector: prelude });
      } else {
        stack.push({ kind: "rule", selector: prelude });
      }
      continue;
    }
    if (ch === "}" && paren === 0) {
      flush();
      stack.pop();
      continue;
    }
    if (ch === ";" && paren === 0) { flush(); continue; }
    buf += ch;
  }
  return out;
}

const isRootSelector = (selector: string) =>
  selector.split(",").every((s) => s.trim().startsWith(":root"));

function violations(decls: Decl[]): Map<string, { kind: Kind; value: string }> {
  const found = new Map<string, { kind: Kind; value: string }>();
  const add = (d: Decl, kind: Kind) => {
    const key = `${d.selector} :: ${kind}`;
    if (!found.has(key)) found.set(key, { kind, value: `${d.prop}: ${d.value}` });
  };
  for (const d of decls) {
    if (GRADIENT.test(d.value)) add(d, "gradient");
    if (d.prop === "box-shadow") {
      const parts = d.value.split(/,(?![^(]*\))/).map((p) => p.trim());
      const ok = d.value.trim() === "none" || parts.every((p) => /^var\(--shadow-[\w-]+\)$/.test(p));
      if (!ok) add(d, "shadow");
    }
    if (d.prop === "font-family") {
      const v = d.value.replace(/\s+/g, " ").trim();
      if (!(v === "inherit" || /^var\(--font-[\w-]+\)$/.test(v) || FONT_STACKS.includes(v))) add(d, "font");
    }
    if (!isRootSelector(d.selector) && COLOUR_LITERAL.test(d.value) && !GRADIENT.test(d.value) && d.prop !== "box-shadow") {
      add(d, "colour");
    }
    // A coloured shadow or gradient also carries literals; they are reported once, as shadow or gradient.
  }
  return found;
}

// Today's violations. This list must only shrink (see the header).
const KNOWN_OFFENDERS: string[] = [
  ".day-strip[data-fade=\"both\"] :: gradient",
  ".day-strip[data-fade=\"end\"] :: gradient",
  ".day-strip[data-fade=\"start\"] :: gradient",
  ".drop-after :: shadow",
  ".drop-before :: shadow",
  ".input:focus :: shadow",
  ".key.over :: gradient",
  ".ledger td.select input[type=\"checkbox\"], .ledger th input[type=\"checkbox\"], .import-table td.select input[type=\"checkbox\"], .import-table th input[type=\"checkbox\"] :: shadow",
  ".ledger td.select input[type=\"checkbox\"]:checked, .ledger th input[type=\"checkbox\"]:checked, .import-table td.select input[type=\"checkbox\"]:checked, .import-table th input[type=\"checkbox\"]:checked :: shadow",
  ".money-seg-planned :: gradient",
  ".month-bar.over :: gradient",
  ".nexus-button.in-bar .nexus-mark .nm-K :: colour",
  ".nexus-button.in-bar .nexus-mark .nm-k, .nexus-button.in-bar .nexus-mark .nm-b :: colour",
  ".quick-ways .btn:focus-within :: shadow",
  ".ring :: gradient",
  ".seg-btn[aria-pressed=\"true\"] :: shadow",
  ".voice-preset[aria-pressed=\"true\"] :: shadow",
];

const found = violations(readDeclarations([CSS_PATH, ...OTHER_CSS].map((f) => readFileSync(f, "utf8")).join("\n")));

describe("styles.css follows DESIGN.md", () => {
  it("reads the token blocks", () => {
    const decls = readDeclarations(readFileSync(CSS_PATH, "utf8"));
    expect(decls.some((d) => isRootSelector(d.selector) && d.prop === "--bg-shell")).toBe(true);
    expect(decls.length).toBeGreaterThan(1000);
  });

  for (const [label, kind] of [
    ["colour literals outside :root", "colour"],
    ["gradients", "gradient"],
    ["box-shadows that are not --shadow-* tokens", "shadow"],
    ["font-family that is not a token or the allowed stack", "font"],
  ] as const) {
    const known = KNOWN_OFFENDERS.filter((k) => k.endsWith(` :: ${kind}`));
    const now = [...found].filter(([, v]) => v.kind === kind);

    it(`has no new ${label}`, () => {
      const fresh = now.filter(([k]) => !known.includes(k)).map(([k, v]) => `${k}  (${v.value})`);
      expect(fresh).toEqual([]);
    });

    it(`has no stale KNOWN_OFFENDERS for ${label} (delete the line)`, () => {
      const stale = known.filter((k) => !found.has(k));
      expect(stale).toEqual([]);
    });
  }
});
