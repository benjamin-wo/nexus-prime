import type { Me } from "../api";
import { MonthPicker } from "../components/MonthPicker";
import { PastBudgets, usePastBudgets } from "../components/PastBudgets";
import { monthLabel } from "../months";
import { useMonthParam } from "../useMonthParam";
import { BillsSection } from "./Bills";
import { BudgetsSection } from "./Budgets";
import { PaydaySection } from "./Payday";
import { SubscriptionsSection } from "./Subscriptions";

/** Budgets, scheduled payments, payday and subscriptions. Settings has the rest. A past
 * month shows only how each budget did that month; limits are changed on this month. */
export function BudgetsPage({ me }: { me: Me }) {
  const { month, current, past, setMonth } = useMonthParam(me.user.timezone);
  const budgets = usePastBudgets(month, past);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Budgets</h1>
          <p className="muted">
            {past
              ? `How each budget did in ${monthLabel(month)}. To change a limit, go to this month.`
              : "Budgets reset on the 1st; nothing rolls over."}
          </p>
        </div>
        <MonthPicker month={month} current={current} onChange={setMonth} />
      </div>
      {past ? (
        <section className="card" aria-labelledby="past-budgets">
          <div className="card-head">
            <h2 id="past-budgets">Budgets</h2>
            <span className="caption">Against today's limits</span>
          </div>
          {budgets.isLoading && <p className="state">Loading…</p>}
          {budgets.isError && <p className="state error-text">Couldn't load that month's budgets.</p>}
          {budgets.data && (
            <PastBudgets budgets={budgets.data} month={month} timezone={me.user.timezone} />
          )}
        </section>
      ) : (
        <div className="plan-grid">
          <BudgetsSection me={me} />
          <BillsSection me={me} />
          <PaydaySection me={me} />
          <SubscriptionsSection />
        </div>
      )}
    </>
  );
}
