import type { Me } from "../api";
import { BillsSection } from "./Bills";
import { BudgetsSection } from "./Budgets";

/** Planning: budgets and bills (and, later, the salary schedule). */
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
      </div>
    </>
  );
}
