/** Line icons drawn in the current text colour. Decorative by default: hidden
 * from screen readers, so the control they sit in must carry its own name.
 * Pass `label` when the icon itself carries meaning (a weather symbol). */
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
  | "mail"
  | "plus"
  | "settings"
  | "up"
  | "down"
  | "chevron"
  | "chevronLeft"
  | "check"
  | "flight"
  | "stay"
  | "train"
  | "ticket"
  | "place"
  | "food"
  | "find"
  | "sun"
  | "partCloud"
  | "cloud"
  | "fog"
  | "snow"
  | "storm"
  | "rain"
  | "walk"
  | "transit"
  | "car"
  | "shield"
  | "warning"
  | "clock"
  | "phone"
  | "info"
  | "order"
  | "landing"
  | "edit"
  | "x";

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
  plus: ["M12 5v14M5 12h14"],
  settings: [
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  ],
  up: ["M7 17L17 7", "M8 7h9v9"],
  down: ["M7 7l10 10", "M17 8v9H8"],
  chevron: ["M9 6l6 6-6 6"],
  chevronLeft: ["M15 6l-6 6 6 6"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  flight: ["M2 16l20-6-2-3-7 2-5-5-2 1 3 6-5 1-2-2-1 1z"],
  stay: ["M3 18V7", "M3 14h18v4", "M21 14v-2a3 3 0 0 0-3-3h-7v5", "M7 11.5h.01"],
  train: [
    "M7 3h10a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V5a2 2 0 0 1 2-2z",
    "M5 10h14",
    "M8 21l2-4M16 21l-2-4",
    "M9 13.5h.01M15 13.5h.01",
  ],
  ticket: ["M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4z", "M14 7v10"],
  place: [
    "M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11z",
    "M12 7.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z",
  ],
  food: ["M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10", "M17 21V3c-2 1-3 4-3 7h3"],
  find: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "M20 20l-4-4"],
  sun: [
    "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  ],
  partCloud: [
    "M8 6.5V4M3.6 8.1 2 6.5M12.4 8.1 14 6.5M2 12h2",
    "M7 20h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 11.1 4.5 4.5 0 0 0 7 20z",
  ],
  cloud: ["M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 9.1 4.5 4.5 0 0 0 7 18z"],
  fog: [
    "M7 14h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 5.1 4.5 4.5 0 0 0 7 14z",
    "M4 17.5h16M7 21h10",
  ],
  snow: [
    "M7 14h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 5.1 4.5 4.5 0 0 0 7 14z",
    "M8 17.5h.01M12 17.5h.01M16 17.5h.01M10 21h.01M14 21h.01",
  ],
  storm: [
    "M7 14h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 5.1 4.5 4.5 0 0 0 7 14z",
    "M12.5 14l-2.5 4h4l-2.5 4",
  ],
  rain: [
    "M7 15h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 6.1 4.5 4.5 0 0 0 7 15z",
    "M9 18l-1 3M13 18l-1 3M17 18l-1 3",
  ],
  walk: [
    "M13 5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
    "M12 8l-3 3 2 3-2 7M12 8l3 3 3 1M11 14l3 3 .5 4",
  ],
  transit: [
    "M6 3h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
    "M4 10h16",
    "M7 21v-3M17 21v-3",
    "M8 14h.01M16 14h.01",
  ],
  car: [
    "M5 16V12l2-5h10l2 5v4z",
    "M3 12h18",
    "M5 16v3h3v-3M16 16v3h3v-3",
    "M8 14h.01M16 14h.01",
  ],
  shield: ["M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"],
  warning: ["M12 3l9.5 17h-19z", "M12 10v4M12 17.5v.01"],
  clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7v5l3 2"],
  phone: [
    "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
  ],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5M12 8h.01"],
  order: ["M8 20V5", "M4.5 8.5L8 5l3.5 3.5", "M16 4v15", "M12.5 15.5L16 19l3.5-3.5"],
  landing: ["M3 20h18", "M3 8l4 1 4 3 5.5 1.5a2 2 0 0 1-.5 3.9L5 15z"],
  edit: ["M4 20h4L19 9l-4-4L4 16z", "M13.5 6.5l4 4"],
  x: ["M6 6l12 12", "M18 6L6 18"],
};

export function Icon({
  name,
  size = 20,
  label,
  className,
}: {
  name: IconName;
  size?: number;
  label?: string;
  className?: string;
}) {
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
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
      className={className}
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
