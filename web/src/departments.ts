/** The departments behind the front desk, as the web app shows them. A department
 * with ``upcoming`` set shows an intro until it's built. */
export type DepartmentTab = { to: string; label: string; end?: boolean };

export type DepartmentView = {
  name: string;
  label: string;
  /** What the bottom bar on a phone calls it, under its icon. */
  short: string;
  icon: string;
  path: string;
  blurb: string;
  tabs: DepartmentTab[];
  upcoming?: string; // what it will do, for a department that isn't ready yet
  /** The preference that puts it in the menu (the nav rail and the bottom bar). Without one it is
   * always there. Its pages open by link either way; only the menu changes. */
  menu?: "show_invest" | "show_travel";
};

/** The preferences that decide what the menu shows. A section turns on only for `true`: not
 * decided (null or absent) and switched off (false) are both hidden. */
export type MenuPreferences = { show_invest?: boolean | null; show_travel?: boolean | null };

/** Whether a department has a place in the menu for someone with these preferences. */
export const inMenu = (d: DepartmentView, preferences?: MenuPreferences): boolean =>
  d.menu === undefined || preferences?.[d.menu] === true;

export const DEPARTMENTS: DepartmentView[] = [
  {
    name: "accounting",
    label: "Money",
    short: "Money",
    icon: "🧾",
    path: "/accounting",
    blurb: "Spending, income, budgets, bills and subscriptions.",
    tabs: [
      { to: "/accounting", label: "Overview", end: true },
      { to: "/accounting/ledger", label: "Ledger" },
      { to: "/accounting/budgets", label: "Budgets" },
      { to: "/accounting/cashflow", label: "Cash flow" },
      // Receipts by email and statement import are Settings' (Connections).
    ],
  },
  {
    name: "investment",
    label: "Investment",
    short: "Invest",
    menu: "show_invest",
    icon: "📈",
    path: "/investment",
    blurb: "Your holdings, and research on when to buy and sell.",
    tabs: [
      { to: "/investment", label: "Portfolio", end: true },
      { to: "/investment/watchlist", label: "Watchlist" },
      { to: "/investment/plans", label: "Trade plans" },
    ],
  },
  {
    name: "travel",
    label: "Travel",
    short: "Travel",
    menu: "show_travel",
    icon: "✈️",
    path: "/travel",
    blurb: "Your trips: budgets, money set aside, spending and settling up.",
    tabs: [{ to: "/travel", label: "Trips", end: true }],
  },
];

export const departmentFor = (path: string) =>
  DEPARTMENTS.find((d) => path === d.path || path.startsWith(`${d.path}/`));
