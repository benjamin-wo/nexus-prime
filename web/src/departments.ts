/** The departments behind the front desk, as the web app shows them. Accounting is
 * live; the others show an intro until they're built (M13 Investment, M11 Travel). */
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
    blurb: "Trips tied to your money: budget, savings, bookings and spending.",
    tabs: [],
    upcoming:
      "Add a trip and Nexus keeps its money together: a budget, how much to set aside each payday, bookings picked up from your email, and what you spend while you're away, with a settle-up with friends at the end. Later it can research where and when to go, linking to sellers; it never books anything.",
  },
];

export const departmentFor = (path: string) =>
  DEPARTMENTS.find((d) => path === d.path || path.startsWith(`${d.path}/`));
