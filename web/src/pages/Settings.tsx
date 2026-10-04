import { CategoriesSection } from "./Categories";
import { EmailCard } from "./Email";
import { MemorySection } from "./Memory";
import { RulesSection } from "./Rules";
import { UpdatesSection } from "./Updates";

/** Account-wide settings, then each department's own. */
export function Settings() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">How Nexus works for you, then each department's own settings.</p>
        </div>
      </div>
      <h2 className="section-title">Account</h2>
      <div className="plan-grid">
        <UpdatesSection />
        <MemorySection />
      </div>
      <h2 className="section-title">
        <span aria-hidden="true">🧾</span> Accounting
      </h2>
      <div className="plan-grid">
        <EmailCard />
        <CategoriesSection />
        <RulesSection />
      </div>
    </>
  );
}
