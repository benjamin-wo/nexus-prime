import { CategoriesSection } from "./Categories";
import { EmailCard } from "./Email";
import { RulesSection } from "./Rules";
import { UpdatesSection } from "./Updates";

/** How Nexus works for you: Telegram updates, email receipts, categories and rules. */
export function Settings() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Updates, email receipts and how expenses are filed.</p>
        </div>
      </div>
      <div className="plan-grid">
        <UpdatesSection />
        <EmailCard />
        <CategoriesSection />
        <RulesSection />
      </div>
    </>
  );
}
