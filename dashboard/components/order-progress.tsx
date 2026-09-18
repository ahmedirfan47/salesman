"use client";

import { Check } from "lucide-react";

const STAGES = ["confirmed", "preparing", "dispatched", "delivered", "completed"] as const;
const LABELS: Record<string, string> = {
  confirmed: "Confirmed",
  preparing: "Preparing",
  dispatched: "Dispatched",
  delivered: "Delivered",
  completed: "Completed",
};

const OFFPATH: Record<string, { label: string; color: string }> = {
  cancelled: { label: "Cancelled", color: "text-red-600 bg-red-50" },
  requires_human_review: { label: "Needs review", color: "text-amber-700 bg-amber-50" },
};

export function OrderProgress({ status, compact = false }: { status: string; compact?: boolean }) {
  if (OFFPATH[status]) {
    const o = OFFPATH[status];
    return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${o.color}`}>{o.label}</span>;
  }

  const currentIndex = STAGES.indexOf(status as (typeof STAGES)[number]);

  if (compact) {
    return (
      <div className="flex items-center gap-1">
        {STAGES.map((stage, i) => {
          const done = i <= currentIndex;
          return (
            <div key={stage} className="flex items-center">
              <div
                title={LABELS[stage]}
                className={`h-2 w-2 rounded-full ${done ? "bg-[var(--primary)]" : "bg-gray-200"}`}
              />
              {i < STAGES.length - 1 && (
                <div className={`h-0.5 w-4 ${i < currentIndex ? "bg-[var(--primary)]" : "bg-gray-200"}`} />
              )}
            </div>
          );
        })}
        <span className="ml-2 text-xs font-medium text-slate-600">{LABELS[status] ?? status}</span>
      </div>
    );
  }

  // Mobile: a "Step X of Y" summary + a single progress bar. A 5-node
  // labeled stepper cannot fit a phone width without either truncating
  // labels or forcing horizontal scroll -- both worse than this pattern,
  // which is how most mobile checkout/status flows handle it.
  const mobileView = (
    <div className="sm:hidden">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-700">{LABELS[status] ?? status}</span>
        <span className="text-xs text-slate-400">
          Step {currentIndex + 1} of {STAGES.length}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-[var(--primary)] transition-all"
          style={{ width: `${((currentIndex + 1) / STAGES.length) * 100}%` }}
        />
      </div>
    </div>
  );

  // Desktop/tablet: the full labeled stepper.
  const desktopView = (
    <div className="hidden sm:flex sm:items-center">
      {STAGES.map((stage, i) => {
        const done = i < currentIndex;
        const current = i === currentIndex;
        return (
          <div key={stage} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold ${
                  done ? "bg-[var(--primary)] text-white"
                  : current ? "border-2 border-[var(--primary)] bg-white text-[var(--primary)]"
                  : "border-2 border-gray-200 bg-white text-gray-300"
                }`}
              >
                {done ? <Check size={16} /> : i + 1}
              </div>
              <span className={`mt-1 text-xs ${current ? "font-semibold text-[var(--primary)]" : done ? "text-slate-600" : "text-slate-300"}`}>
                {LABELS[stage]}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div className={`mx-2 h-0.5 flex-1 ${i < currentIndex ? "bg-[var(--primary)]" : "bg-gray-200"}`} />
            )}
          </div>
        );
      })}
    </div>
  );

  return (
    <div>
      {mobileView}
      {desktopView}
    </div>
  );
}