import { useEffect, useRef, useState } from "react";

/** The user asked their device for less motion. */
export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

// What rises into view as it's scrolled to: cards and the panels laid out like them.
const REVEALED = ".card, .assistant, .trip-card, .next-pass, .stay-card, .dept-tabs";
const STAGGER_MS = 35;
const MAX_STAGGER = 3;

/** Cards under ``root`` fade and rise into place the first time they're scrolled
 * into view, a few at a time, as on a landing page. Bars and rings inside them fill
 * as they arrive (styles.css). Nothing moves for reduced motion. */
export function useReveal(root: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const host = root.current;
    if (!host || reducedMotion() || typeof IntersectionObserver === "undefined") return;
    const seen = new IntersectionObserver(
      (entries) => {
        const arriving = entries.filter((e) => e.isIntersecting).map((e) => e.target as HTMLElement);
        arriving.forEach((el, i) => {
          el.style.setProperty("--reveal-delay", `${Math.min(i, MAX_STAGGER) * STAGGER_MS}ms`);
          el.dataset.reveal = "in";
          seen.unobserve(el);
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -4% 0px" },
    );
    const watch = () => {
      host.querySelectorAll<HTMLElement>(REVEALED).forEach((el) => {
        // Inside a card that's already rising, or met before: leave it be.
        if (el.dataset.reveal || el.parentElement?.closest("[data-reveal]")) return;
        el.dataset.reveal = "pending";
        seen.observe(el);
      });
    };
    watch();
    let frame = 0;
    const changes = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(watch);
    });
    changes.observe(host, { childList: true, subtree: true });
    return () => {
      cancelAnimationFrame(frame);
      changes.disconnect();
      seen.disconnect();
    };
  }, [root]);
}

const NUMBER = /-?\d[\d,]*(?:\.\d+)?/;

/** A formatted figure ("S$1,234.50", "71%") counting up from zero to its value the
 * first time it's seen, keeping its format. A placeholder ("…") shows as it is, and
 * the count starts once a number arrives. Shows the value at once for reduced
 * motion, and whenever the value changes after the count. */
export function CountUp({ value, ms = 650 }: { value: string; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const match = value.match(NUMBER);
  const has = match !== null;
  // How far through the count, 0 to 1; null shows the value as it is.
  const [progress, setProgress] = useState<number | null>(null);
  const started = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!has || started.current || !el || reducedMotion() || typeof IntersectionObserver === "undefined") return;
    started.current = true;
    setProgress(0);
    let frame = 0;
    const run = () => {
      const start = performance.now();
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / ms);
        setProgress(t < 1 ? 1 - Math.pow(1 - t, 3) : null);
        if (t < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    const seen = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        seen.disconnect();
        run();
      }
    });
    seen.observe(el);
    return () => {
      seen.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [has, ms]);

  if (progress === null || !match) return <span ref={ref}>{value}</span>;
  const target = Number(match[0].replace(/,/g, ""));
  const decimals = match[0].split(".")[1]?.length ?? 0;
  const middle = (target * progress).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: match[0].includes(","),
  });
  return <span ref={ref}>{value.replace(match[0], middle)}</span>;
}

/** A heading whose last word is set in the italic serif, as an accent. */
export function AccentTitle({ text }: { text: string }) {
  const cut = text.lastIndexOf(" ");
  if (cut < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, cut + 1)}
      <em className="accent-serif">{text.slice(cut + 1)}</em>
    </>
  );
}
