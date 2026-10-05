/** The departments behind the front desk, as the web app shows them. A department
 * with ``upcoming`` set shows an intro until it's built. */
export type DepartmentTab = { to: string; label: string; end?: boolean };

export type DepartmentView = {
  name: string;
  label: string;
  icon: string;
  path: string;
  blurb: string;
  tabs: DepartmentTab[];
  upcoming?: string; // what it will do, for a department that isn't ready yet
};

export const DEPARTMENTS: DepartmentView[] = [
  {
    name: "accounting",
    label: "Accounting",
    icon: "🧾",
    path: "/accounting",
    blurb: "Spending, income, budgets, bills, subscriptions, email receipts and statements.",
    tabs: [
      { to: "/accounting", label: "Overview", end: true },
      { to: "/accounting/ledger", label: "Ledger" },
      { to: "/accounting/plan", label: "Plan" },
      { to: "/accounting/cashflow", label: "Cash flow" },
      { to: "/accounting/email", label: "Email" },
      { to: "/accounting/import", label: "Import" },
    ],
  },
  {
    name: "investment",
    label: "Investment",
    icon: "📈",
    path: "/investment",
    blurb: "Your holdings, and research on when to buy and sell.",
    tabs: [
      { to: "/investment", label: "Portfolio", end: true },
      { to: "/investment/watchlist", label: "Watchlist" },
      { to: "/investment/plans", label: "Plans" },
    ],
  },
  {
    name: "travel",
    label: "Travel",
    icon: "✈️",
    path: "/travel",
    blurb: "Your trips: budgets, money set aside, spending and settling up.",
    tabs: [{ to: "/travel", label: "Trips", end: true }],
  },
];

export const departmentFor = (path: string) =>
  DEPARTMENTS.find((d) => path === d.path || path.startsWith(`${d.path}/`));
