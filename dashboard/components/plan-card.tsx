"use client";

import Link from "next/link";
import { Check, Minus, Plus } from "lucide-react";
import { INCLUDED_FEATURES, PRICING, formatMoney, quote } from "@/lib/plans";

interface Props {
  branches: number;
  onBranchesChange: (n: number) => void;
  /** Primary CTA -- a mailto: or an in-app route. */
  primaryLabel: string;
  primaryHref: string;
  /** Optional secondary CTA, e.g. "Talk to sales". */
  secondaryLabel?: string;
  secondaryHref?: string;
}

/**
 * The one place the Salesman price card is drawn. Used by both the public
 * /plans page and the authenticated /billing page so they cannot drift apart.
 */
export function PlanCard({ branches, onBranchesChange, primaryLabel, primaryHref, secondaryLabel, secondaryHref }: Props) {
  const q = quote(branches);
  const isExternal = (href: string) => href.startsWith("mailto:") || href.startsWith("http");

  const primaryClass = "block w-full rounded-full bg-[var(--primary)] py-2.5 text-center text-sm font-medium text-white transition hover:opacity-90";
  const secondaryClass = "block w-full rounded-full border border-[var(--border-strong,#d5d8e0)] py-2.5 text-center text-sm font-medium text-slate-900 transition hover:bg-gray-50";

  return (
    <div className="grid gap-0 overflow-hidden rounded-2xl border border-[var(--primary)] bg-white shadow-sm md:grid-cols-[1.1fr_1fr]">
      <div className="p-6 sm:p-8">
        <h2 className="text-xl font-bold">Salesman</h2>
        <p className="mt-1 text-sm text-slate-500">One plan, priced per branch. Everything included.</p>

        <div className="mt-6 grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-slate-400">Setup, per branch</div>
            <div className="mt-1 text-3xl font-bold">{formatMoney(PRICING.setupPerBranch)}</div>
            <div className="text-xs text-slate-400">one-time</div>
          </div>
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-slate-400">Monthly, per branch</div>
            <div className="mt-1 text-3xl font-bold">{formatMoney(PRICING.monthlyPerBranch)}</div>
            <div className="text-xs text-slate-400">per month</div>
          </div>
        </div>

        <ul className="mt-6 space-y-3">
          {INCLUDED_FEATURES.map((f) => (
            <li key={f} className="flex items-start gap-2.5 text-sm text-slate-600">
              <Check size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />
              {f}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col border-t border-[var(--border)] bg-gray-50 p-6 sm:p-8 md:border-l md:border-t-0">
        <div className="text-sm font-medium text-slate-700">How many branches?</div>
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={() => onBranchesChange(q.branches - 1)}
            disabled={q.branches <= 1}
            aria-label="Fewer branches"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-white transition hover:bg-gray-100 disabled:opacity-40"
          >
            <Minus size={16} />
          </button>
          <div className="w-14 text-center text-2xl font-bold tabular-nums" aria-live="polite">{q.branches}</div>
          <button
            onClick={() => onBranchesChange(q.branches + 1)}
            disabled={q.branches >= PRICING.maxBranches}
            aria-label="More branches"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-white transition hover:bg-gray-100 disabled:opacity-40"
          >
            <Plus size={16} />
          </button>
        </div>

        <dl className="mt-6 space-y-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-500">Setup ({q.branches} × {formatMoney(PRICING.setupPerBranch)})</dt>
            <dd className="font-semibold tabular-nums">{formatMoney(q.setup)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Monthly ({q.branches} × {formatMoney(PRICING.monthlyPerBranch)})</dt>
            <dd className="font-semibold tabular-nums">{formatMoney(q.monthly)}/mo</dd>
          </div>
          <div className="flex justify-between border-t border-[var(--border)] pt-3">
            <dt className="font-medium text-slate-700">First year total</dt>
            <dd className="text-lg font-bold tabular-nums">{formatMoney(q.firstYear)}</dd>
          </div>
        </dl>

        <div className="mt-auto space-y-3 pt-8">
          {isExternal(primaryHref) ? (
            <a href={primaryHref} className={primaryClass}>{primaryLabel}</a>
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
        <p className="mt-4 text-center text-xs text-slate-400">Prices in {PRICING.currency}, excluding VAT.</p>
      </div>
    </div>
  );
}