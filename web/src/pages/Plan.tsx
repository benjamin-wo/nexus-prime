import type { Me } from "../api";
import { BillsSection } from "./Bills";
import { BudgetsSection } from "./Budgets";
import { EmailCard } from "./Email";
import { PaydaySection } from "./Payday";
import { RulesSection } from "./Rules";
import { SubscriptionsSection } from "./Subscriptions";
import { UpdatesSection } from "./Updates";

/** Planning: budgets, bills, payday, subscriptions, category rules and Telegram updates. */
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
        <SubscriptionsSection />
        <RulesSection />
        <UpdatesSection />
        <EmailCard />
      </div>
    </>
  );
}
