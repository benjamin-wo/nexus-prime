import { earliestMonth, type MonthKey, monthLabel, shiftMonth } from "../months";
import { Icon } from "./Icon";

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
      <button
        type="button"
        className="btn btn-ghost month-step"
        aria-label="Previous month"
        disabled={month <= earliestMonth(current)}
        onClick={() => onChange(shiftMonth(month, -1))}
      >
        <Icon name="chevronLeft" size={18} />
      </button>
      <span className="month-picker-label" aria-live="polite" aria-atomic="true">
        {monthLabel(month)}
      </span>
      <button
        type="button"
        className="btn btn-ghost month-step"
        aria-label="Next month"
        disabled={month >= current}
        onClick={() => onChange(shiftMonth(month, 1))}
      >
        <Icon name="chevron" size={18} />
      </button>
    </div>
  );
}
