/** Line icons drawn in the current text colour. Decorative: always hidden from
 * screen readers, so the control they sit in must carry its own name. */
export type IconName =
  | "home"
  | "accounting"
  | "investment"
  | "travel"
  | "sparkle"
  | "send"
  | "camera"
  | "receipt"
  | "target"
  | "alert"
  | "calendar"
  | "mail";

const PATHS: Record<IconName, string[]> = {
  home: ["M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"],
  accounting: [
    "M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
    "M8 8h8M8 12h8M8 16h5",
  ],
  investment: ["M3 17l6-6 4 4 8-8", "M15 7h6v6"],
  travel: ["M2 16l20-6-2-3-7 2-5-5-2 1 3 6-5 1-2-2-1 1z"],
  sparkle: [
    "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z",
    "M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  ],
  send: ["M5 12h14", "M13 6l6 6-6 6"],
  camera: [
    "M4 8h3l2-3h6l2 3h3v11H4z",
    "M12 16.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
  ],
  receipt: ["M6 3h12v18l-3-2-3 2-3-2-3 2z", "M9 8h6M9 12h6"],
  target: [
    "M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16z",
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  ],
  alert: ["M12 3l9.5 17h-19z", "M12 10v4M12 17.5v.01"],
  calendar: ["M4 6h16v14H4z", "M4 10h16M8 3v4M16 3v4"],
  mail: ["M3 5h18v14H3z", "M3 7l9 6 9-6"],
};

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** The nav icon for a department, by its name. */
export function departmentIcon(name: string): IconName {
  return name === "accounting" || name === "investment" || name === "travel"
    ? name
    : "home";
}
