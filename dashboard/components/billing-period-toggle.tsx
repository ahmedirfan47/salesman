import type { BillingPeriod } from "@/lib/plans";
import { annualSavingsPercent } from "@/lib/plans";

export function BillingPeriodToggle({
  value,
  onChange,
}: {
  value: BillingPeriod;
  onChange: (p: BillingPeriod) => void;
}) {
  const savings = annualSavingsPercent();
  return (
    <div className="inline-flex rounded-full border border-[var(--border)] bg-gray-50 p-1">
      {(["monthly", "annual"] as BillingPeriod[]).map((p) => {
        const active = value === p;
        return (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-medium transition ${
              active ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            {p === "monthly" ? "Monthly" : "Annual"}
            {p === "annual" && (
              <span
                className={`rounded px-1.5 py-0.5 text-xs ${
                  active ? "bg-indigo-50 text-[var(--primary)]" : "bg-gray-200 text-slate-500"
                }`}
              >
                −{savings}%
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}