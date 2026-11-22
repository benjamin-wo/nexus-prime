import { earliestMonth, type MonthKey, monthLabel, shiftMonth } from "../months";
import { Icon } from "./Icon";
import { Button } from "./ui";

/** "‹ October 2026 ›": steps a page through months, from two years back to the current
 * one (never a future month). The month is a live region, so a screen reader hears it
 * change. */
export function MonthPicker({
  month,
  current,
  onChange,
}: {
  month: MonthKey;
  current: MonthKey;
  onChange: (month: MonthKey) => void;
}) {
  return (
    <div className="month-picker" role="group" aria-label="Month">
      <Button
        variant="text"
        className="month-step"
        aria-label="Previous month"
        disabled={month <= earliestMonth(current)}
        onClick={() => onChange(shiftMonth(month, -1))}
      >
        <Icon name="chevronLeft" size={18} />
      </Button>
      <span className="month-picker-label" aria-live="polite" aria-atomic="true">
        {monthLabel(month)}
      </span>
      <Button
        variant="text"
        className="month-step"
        aria-label="Next month"
        disabled={month >= current}
        onClick={() => onChange(shiftMonth(month, 1))}
      >
        <Icon name="chevron" size={18} />
      </Button>
    </div>
  );
}
