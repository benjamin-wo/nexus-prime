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
    tabs: [],
    upcoming:
      "Send a screenshot of your IBKR portfolio and Nexus keeps your holdings, values them daily in your home currency, and has a research team suggest entry, stop and target levels for days-to-weeks trades, with every number and news point traced to its source. Research only: it never places a trade.",
  },
  {
    name: "travel",
    label: "Travel",
    icon: "✈️",
    path: "/travel",
    blurb: "Trips planned around your budget.",
    tabs: [],
    upcoming:
      "Tell Nexus where and roughly when, and it works out when to go, flights, places to stay and things to do, then shows what the trip costs against your own budget. It never books anything: every result links to the seller.",
  },
];

export const departmentFor = (path: string) =>
  DEPARTMENTS.find((d) => path === d.path || path.startsWith(`${d.path}/`));
