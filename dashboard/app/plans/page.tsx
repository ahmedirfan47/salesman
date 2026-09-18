"use client";

import { useState } from "react";
import Link from "next/link";
import { plans, type BillingPeriod } from "@/lib/plans";
import { BillingPeriodToggle } from "@/components/billing-period-toggle";
import { PlanCard } from "@/components/plan-card";

export default function PublicPlansPage() {
  const [period, setPeriod] = useState<BillingPeriod>("annual");

  return (
    <div className="min-h-screen bg-white">
      <header className="flex items-center justify-between border-b border-[var(--border)] px-6 py-4">
        <Link href="/" className="text-lg font-bold">
          Salesman<span className="text-[var(--primary)]">.</span>
        </Link>
        <Link href="/login" className="rounded-full border border-[var(--border)] px-4 py-1.5 text-sm font-medium hover:bg-gray-50">
          Sign in
        </Link>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-12">
        <h1 className="text-center text-3xl font-bold sm:text-4xl">Choose your plan</h1>
        <p className="mx-auto mt-3 max-w-md text-center text-slate-500">
          Start free. Upgrade when you're ready to run deliveries at scale.
        </p>

        <div className="mt-8 flex justify-center">
          <BillingPeriodToggle value={period} onChange={setPeriod} />
        </div>

        <div className="mt-10 grid grid-cols-1 gap-6 lg:grid-cols-3">
          {plans.map((plan) => (
            <PlanCard key={plan.id} plan={plan} period={period} actionHref="/login" />
          ))}
        </div>
      </div>
    </div>
  );
}