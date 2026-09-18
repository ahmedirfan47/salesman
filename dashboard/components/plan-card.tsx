import Link from "next/link";
import { Check } from "lucide-react";
import type { BillingPeriod, Plan } from "@/lib/plans";

interface Props {
  plan: Plan;
  period: BillingPeriod;
  /** Billing page: true when this is the org's current plan (disables the button). */
  isCurrent?: boolean;
  /** Public /plans page: renders the CTA as a Link to this href. */
  actionHref?: string;
  /** Billing page: renders the CTA as a button calling this instead. */
  onAction?: () => void;
}

/**
 * The one place a pricing card is drawn. Used by both the public /plans
 * page and the authenticated /billing page -- change the look once here
 * instead of in two files that can quietly drift apart.
 */
export function PlanCard({ plan, period, isCurrent, actionHref, onAction }: Props) {
  const price = period === "annual" ? plan.annualMonthly : plan.monthly;
  const ctaLabel = isCurrent
    ? "Current plan"
    : plan.free
    ? actionHref
      ? "Get started free"
      : "Downgrade to Free"
    : `Choose ${plan.name}`;

  const ctaClasses = `mt-6 block w-full rounded-full py-2.5 text-center text-sm font-medium transition ${
    isCurrent
      ? "cursor-default border border-[var(--border)] text-slate-400"
      : plan.recommended
      ? "bg-[var(--primary)] text-white hover:opacity-90"
      : "border border-[var(--border-strong,#d5d8e0)] text-slate-900 hover:bg-gray-50"
  }`;

  return (
    <div
      className={`flex flex-col rounded-2xl border bg-white p-6 ${
        plan.recommended ? "border-[var(--primary)] shadow-sm" : "border-[var(--border)]"
      }`}
    >
      {plan.recommended && (
        <span className="mb-3 self-start rounded-md bg-[var(--primary)] px-2 py-1 text-xs font-semibold text-white">
          MOST POPULAR
        </span>
      )}
      <h2 className="text-xl font-bold">{plan.name}</h2>
      <p className="mt-1 text-sm text-slate-500">{plan.tagline}</p>

      <div className="mt-5 flex items-baseline gap-1">
        {plan.free ? (
          <span className="text-4xl font-bold">Free</span>
        ) : (
          <>
            <span className="text-sm text-slate-500">{plan.currency}</span>
            <span className="text-4xl font-bold">{price}</span>
            <span className="text-sm text-slate-500">/mo</span>
          </>
        )}
      </div>
      {!plan.free && period === "annual" && (
        <p className="mt-1 text-xs text-slate-400">billed annually</p>
      )}

      <ul className="mt-6 flex-1 space-y-3">
        {plan.features.map((f) => (
          <li key={f} className="flex items-start gap-2.5 text-sm text-slate-600">
            <Check size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />
            {f}
          </li>
        ))}
      </ul>

      {actionHref ? (
        <Link href={actionHref} className={ctaClasses}>
          {ctaLabel}
        </Link>
      ) : (
        <button onClick={onAction} disabled={isCurrent} className={ctaClasses}>
          {ctaLabel}
        </button>
      )}
    </div>
  );
}