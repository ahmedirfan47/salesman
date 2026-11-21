"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, Minus, Plus } from "lucide-react";
import { CURRENCY, INCLUDED_FEATURES, PLANS, PlanKey, clampBranches, formatMoney, planByKey, quote } from "@/lib/plans";

interface Props {
  branches: number;
  onBranchesChange: (n: number) => void;
  /** Primary CTA -- a mailto: or an in-app route. The chosen plan is added to a mailto subject. */
  primaryLabel: string;
  primaryHref: string;
  /** Optional secondary CTA, e.g. "Create an account". */
  secondaryLabel?: string;
  secondaryHref?: string;
  initialPlan?: PlanKey;
}

/**
 * The one place Salesman's plans are drawn. Used by both the public /plans
 * page and the authenticated /billing page so they cannot drift apart.
 */
export function PlanCard({
  branches, onBranchesChange, primaryLabel, primaryHref, secondaryLabel, secondaryHref, initialPlan = "pilot",
}: Props) {
  const [selected, setSelected] = useState<PlanKey>(initialPlan);
  const plan = planByKey(selected);
  const q = quote(selected, branches);
  const isExternal = (href: string) => href.startsWith("mailto:") || href.startsWith("http");
  const withPlan = (href: string) =>
    href.startsWith("mailto:") && href.includes("subject=")
      ? href.replace("subject=", `subject=${encodeURIComponent(`${plan.name} plan — `)}`)
      : href;

  function choose(key: PlanKey) {
    setSelected(key);
    const p = planByKey(key);
    if (branches !== clampBranches(p, branches)) onBranchesChange(clampBranches(p, branches));
  }

  const primaryClass = "block w-full rounded-full bg-[var(--primary)] py-2.5 text-center text-sm font-medium text-white transition hover:opacity-90";
  const secondaryClass = "block w-full rounded-full border border-[var(--border-strong,#d5d8e0)] py-2.5 text-center text-sm font-medium text-slate-900 transition hover:bg-gray-50";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        {PLANS.map((p) => {
          const active = p.key === selected;
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => choose(p.key)}
              aria-pressed={active}
              className={`flex flex-col rounded-2xl border bg-white p-5 text-left transition ${
                active ? "border-[var(--primary)] ring-2 ring-indigo-100" : "border-[var(--border)] hover:border-slate-300"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-lg font-bold">{p.name}</span>
                {p.highlight && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-[var(--primary)]">Most chosen</span>
                )}
              </div>
              <p className="mt-1 text-sm text-slate-500">{p.tagline}</p>
              <div className="mt-4">
                <span className="text-3xl font-bold">{formatMoney(p.monthlyPerBranch)}</span>
                <span className="text-sm text-slate-500"> /branch/month</span>
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {p.setupPerBranch === 0 ? "No setup fee" : `Setup ${formatMoney(p.setupPerBranch)} per branch, one-time`}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {p.includedOrders === null
                  ? "Unlimited orders"
                  : `${p.includedOrders.toLocaleString("en-US")} orders/branch/month included, then ${formatMoney(p.overagePerOrder ?? 0)} each`}
              </div>
              <ul className="mt-4 space-y-2">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm text-slate-600">
                    <Check size={15} className="mt-0.5 shrink-0 text-[var(--primary)]" />
                    {f}
                  </li>
                ))}
              </ul>
            </button>
          );
        })}
      </div>

      <div className="grid gap-0 overflow-hidden rounded-2xl border border-[var(--border)] bg-white md:grid-cols-[1.1fr_1fr]">
        <div className="p-6 sm:p-8">
          <h2 className="text-sm font-semibold text-slate-500">EVERY PLAN INCLUDES</h2>
          <ul className="mt-4 space-y-3">
            {INCLUDED_FEATURES.map((f) => (
              <li key={f} className="flex items-start gap-2.5 text-sm text-slate-600">
                <Check size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />
                {f}
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col border-t border-[var(--border)] bg-gray-50 p-6 sm:p-8 md:border-l md:border-t-0">
          <div className="text-sm font-medium text-slate-700">{plan.name}: how many branches?</div>
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={() => onBranchesChange(q.branches - 1)}
              disabled={q.branches <= plan.minBranches}
              aria-label="Fewer branches"
              className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-white transition hover:bg-gray-100 disabled:opacity-40"
            >
              <Minus size={16} />
            </button>
            <div className="w-14 text-center text-2xl font-bold tabular-nums" aria-live="polite">{q.branches}</div>
            <button
              onClick={() => onBranchesChange(q.branches + 1)}
              disabled={q.branches >= plan.maxBranches}
              aria-label="More branches"
              className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-white transition hover:bg-gray-100 disabled:opacity-40"
            >
              <Plus size={16} />
            </button>
          </div>
          {plan.minBranches > 1 && <p className="mt-2 text-xs text-slate-500">From {plan.minBranches} branches.</p>}

          <dl className="mt-6 space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Setup ({q.branches} × {formatMoney(plan.setupPerBranch)})</dt>
              <dd className="font-semibold tabular-nums">{formatMoney(q.setup)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Monthly ({q.branches} × {formatMoney(plan.monthlyPerBranch)})</dt>
              <dd className="font-semibold tabular-nums">{formatMoney(q.monthly)}/mo</dd>
            </div>
            <div className="flex justify-between border-t border-[var(--border)] pt-3">
              <dt className="font-medium text-slate-700">{selected === "pilot" ? "Pilot total (60 days)" : "First year total"}</dt>
              <dd className="text-lg font-bold tabular-nums">{formatMoney(q.firstYear)}</dd>
            </div>
          </dl>

          <div className="mt-auto space-y-3 pt-8">
            {isExternal(primaryHref) ? (
              <a href={withPlan(primaryHref)} className={primaryClass}>{primaryLabel}</a>
            ) : (
              <Link href={primaryHref} className={primaryClass}>{primaryLabel}</Link>
            )}
            {secondaryLabel && secondaryHref && (
              isExternal(secondaryHref) ? (
                <a href={secondaryHref} className={secondaryClass}>{secondaryLabel}</a>
              ) : (
                <Link href={secondaryHref} className={secondaryClass}>{secondaryLabel}</Link>
              )
            )}
          </div>
          <p className="mt-4 text-center text-xs text-slate-400">Prices in {CURRENCY}, excluding VAT.</p>
        </div>
      </div>
    </div>
  );
}
