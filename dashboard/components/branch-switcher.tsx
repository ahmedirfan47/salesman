"use client";

import { Building2 } from "lucide-react";
import { useBranches } from "@/lib/branches";

/** Owners/admins pick a branch (or all); branch staff just see which branch they're in. */
export function BranchSwitcher({ onChange }: { onChange?: () => void }) {
  const { branches, current, setCurrent, canSwitch, nameOf } = useBranches();
  const active = branches.filter((b) => b.is_active);

  if (!canSwitch) {
    const name = nameOf(current);
    if (!name) return null;
    return (
      <div className="mx-3 mb-3 flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm text-slate-600">
        <Building2 size={16} className="text-slate-400" /> {name}
      </div>
    );
  }
  if (active.length < 2) return null;

  return (
    <label className="mx-3 mb-3 flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5">
      <Building2 size={16} className="shrink-0 text-slate-400" />
      <span className="sr-only">Branch</span>
      <select
        value={current}
        onChange={(e) => { setCurrent(e.target.value); onChange?.(); }}
        className="w-full bg-transparent py-0.5 text-sm font-medium text-slate-700 outline-none"
      >
        <option value="">All branches</option>
        {active.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
      </select>
    </label>
  );
}