import { CategoriesSection } from "./Categories";
import { EmailCard } from "./Email";
import { MemorySection } from "./Memory";
import { RulesSection } from "./Rules";
import { UpdatesSection } from "./Updates";

/** How Nexus works for you: Telegram updates, email receipts, categories, rules and memory. */
export function Settings() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Updates, email receipts, how expenses are filed and what Nexus remembers.</p>
        </div>
      </div>
      <div className="plan-grid">
        <UpdatesSection />
        <EmailCard />
        <CategoriesSection />
        <RulesSection />
        <MemorySection />
      </div>
    </>
  );
}
