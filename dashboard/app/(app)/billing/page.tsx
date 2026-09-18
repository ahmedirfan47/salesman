"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { plans, type BillingPeriod } from "@/lib/plans";
import { BillingPeriodToggle } from "@/components/billing-period-toggle";
import { PlanCard } from "@/components/plan-card";

// TODO(billing): read the tenant's real subscription once billing is wired.
const CURRENT_PLAN_ID = "free";

export default function BillingPage() {
  const [period, setPeriod] = useState<BillingPeriod>("annual");
  const [notice, setNotice] = useState<string | null>(null);

  function handleChoose(planId: string, planName: string, free?: boolean) {
    if (planId === CURRENT_PLAN_ID) return;
    setNotice(
      free
        ? "Downgrading isn't connected yet — contact support to change your plan."
        : `Upgrading to ${planName} isn't connected yet — contact support to get started.`
    );
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Billing &amp; Plan</h1>
      <p className="mb-6 text-sm text-slate-500">
        Choose the plan that fits your operation. Prices exclude VAT, billed in USD.
      </p>

      {notice && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <Info size={18} className="mt-0.5 shrink-0 text-amber-600" />
          <p className="text-sm text-amber-800">{notice}</p>
        </div>
      )}

      <div className="mb-8">
        <BillingPeriodToggle value={period} onChange={setPeriod} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            period={period}
            isCurrent={plan.id === CURRENT_PLAN_ID}
            onAction={() => handleChoose(plan.id, plan.name, plan.free)}
          />
        ))}
      </div>

      <p className="mt-6 text-center text-xs text-slate-400">
        Changing plans takes effect immediately. Cancel anytime. Limits apply per organization.
      </p>
    </div>
  );
}