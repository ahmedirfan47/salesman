"use client";

import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";

type Period = "monthly" | "annual";
interface Plan {
  id: string; name: string; tagline: string;
  monthly: number; annualMonthly: number;
  free?: boolean; recommended?: boolean; features: string[];
}

const plans: Plan[] = [
  { id: "free", name: "Free", tagline: "Get your catalog and orders out of spreadsheets",
    monthly: 0, annualMonthly: 0, free: true,
    features: ["Up to 50 orders / month", "AI ordering agent over WhatsApp", "Live pricing & inventory", "Up to 2 team members", "Community support"] },
  { id: "growth", name: "Growth", tagline: "For distributors running a delivery fleet",
    monthly: 35, annualMonthly: 29, recommended: true,
    features: ["Up to 2,000 orders / month", "Everything in Free", "Delivery zones & auto-assignment", "Driver & dispatcher apps", "Unlimited team members", "Daily reports & print queue", "Priority support"] },
  { id: "scale", name: "Scale", tagline: "For multi-branch and high-volume operations",
    monthly: 200, annualMonthly: 167,
    features: ["Unlimited orders", "Everything in Growth", "Multi-branch operations", "Cost & margin analytics", "Dedicated onboarding", "Custom integrations", "SLA & account manager"] },
];

export default function PublicPlansPage() {
  const [period, setPeriod] = useState<Period>("annual");
  const savings = Math.round(((35 - 29) / 35) * 100);

  return (
    <div className="min-h-screen bg-white">
      {/* Public top bar -- no sidebar, this page has no auth requirement */}
      <header className="flex items-center justify-between border-b px-6 py-4">
        <Link href="/" className="text-lg font-bold">Salesman<span className="text-[var(--primary)]">.</span></Link>
        <Link href="/login" className="rounded-full border px-4 py-1.5 text-sm font-medium hover:bg-gray-50">
          Sign in
        </Link>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-12">
        <h1 className="text-center text-3xl font-bold sm:text-4xl">Choose your plan</h1>
        <p className="mx-auto mt-3 max-w-md text-center text-slate-500">
          Start free. Upgrade when you're ready to run deliveries at scale.
        </p>

        <div className="mt-8 flex justify-center">
          <div className="inline-flex rounded-full border bg-gray-50 p-1">
            {(["monthly", "annual"] as Period[]).map((p) => {
              const active = period === p;
              return (
                <button key={p} onClick={() => setPeriod(p)}
                  className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-medium ${active ? "bg-white shadow-sm" : "text-slate-500"}`}>
                  {p === "monthly" ? "Monthly" : "Annual"}
                  {p === "annual" && (
                    <span className={`rounded px-1.5 py-0.5 text-xs ${active ? "bg-indigo-50 text-[var(--primary)]" : "bg-gray-200"}`}>−{savings}%</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-6 lg:grid-cols-3">
          {plans.map((plan) => {
            const price = period === "annual" ? plan.annualMonthly : plan.monthly;
            return (
              <div key={plan.id} className={`flex flex-col rounded-2xl border p-6 ${plan.recommended ? "border-[var(--primary)] shadow-sm" : ""}`}>
                {plan.recommended && (
                  <span className="mb-3 self-start rounded-md bg-[var(--primary)] px-2 py-1 text-xs font-semibold text-white">MOST POPULAR</span>
                )}
                <h2 className="text-xl font-bold">{plan.name}</h2>
                <p className="mt-1 text-sm text-slate-500">{plan.tagline}</p>
                <div className="mt-5 flex items-baseline gap-1">
                  {plan.free ? <span className="text-4xl font-bold">Free</span> : (
                    <><span className="text-sm text-slate-500">USD</span><span className="text-4xl font-bold">{price}</span><span className="text-sm text-slate-500">/mo</span></>
                  )}
                </div>
                {!plan.free && period === "annual" && <p className="mt-1 text-xs text-slate-400">billed annually</p>}
                <ul className="mt-6 flex-1 space-y-3">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2.5 text-sm text-slate-600">
                      <Check size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />{f}
                    </li>
                  ))}
                </ul>
                {/* TODO(signup): once a self-serve signup flow exists, send free/paid
                    plans there with ?plan= pre-selected. Until then, every CTA goes
                    to sign-in since accounts are currently created via /docs. */}
                <Link href="/login"
                  className={`mt-6 w-full rounded-full py-2.5 text-center text-sm font-medium ${plan.recommended ? "bg-[var(--primary)] text-white hover:opacity-90" : "border hover:bg-gray-50"}`}>
                  {plan.free ? "Get started free" : `Choose ${plan.name}`}
                </Link>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}