import type { Me } from "../api";
import { BillsSection } from "./Bills";
import { BudgetsSection } from "./Budgets";
import { PaydaySection } from "./Payday";
import { RulesSection } from "./Rules";

/** Planning: budgets, bills, payday and category rules. */
export function Plan({ me }: { me: Me }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Plan</h1>
          <p className="muted">Budgets reset on the 1st; nothing rolls over.</p>
        </div>
      </div>
      <div className="plan-grid">
        <BudgetsSection me={me} />
        <BillsSection me={me} />
        <PaydaySection me={me} />
        <RulesSection />
      </div>
    </>
  );
}
