"use client";

import { Eye } from "lucide-react";
import { useMe } from "@/lib/use-me";
import { SALES_EMAIL } from "@/lib/plans";

/** Shown on every page when signed in with the read-only demo account. */
export function DemoBanner() {
  const { me } = useMe();
  if (me?.role !== "demo") return null;

  return (
    <div className="mb-6 flex flex-col gap-2 rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-slate-700 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-2">
        <Eye size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />
        <span>
          You&apos;re viewing a <b>read-only demo</b> with sample data. Explore every screen; changes are switched off.
        </span>
      </div>
      <a
        href={`mailto:${SALES_EMAIL}?subject=${encodeURIComponent("Salesman pilot")}`}
        className="shrink-0 font-medium text-[var(--primary)] hover:underline"
      >
        Talk to us about a pilot →
      </a>
    </div>
  );
}