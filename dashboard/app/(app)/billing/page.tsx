"use client";

import { useState } from "react";
import { Check, Info } from "lucide-react";
import { Card } from "@/components/ui/card";

type Period = "monthly" | "annual";

interface Plan {
  id: string;
  name: string;
  tagline: string;
  monthly: number;
  annualMonthly: number;
  free?: boolean;
  recommended?: boolean;
  features: string[];
}

const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    tagline: "Get your catalog and orders out of spreadsheets",
    monthly: 0,
    annualMonthly: 0,
    free: true,
    features: [
      "Up to 50 orders / month",
      "AI ordering agent over WhatsApp",
      "Live pricing & inventory",
      "Up to 2 team members",
      "Community support",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    tagline: "For distributors running a delivery fleet",
    monthly: 35,
    annualMonthly: 29,
    recommended: true,
    features: [
      "Up to 2,000 orders / month",
      "Everything in Free",
      "Delivery zones & auto-assignment",
      "Driver & dispatcher apps",
      "Unlimited team members",
      "Daily reports & print queue",
      "Priority support",
    ],
  },
  {
    id: "scale",
    name: "Scale",
    tagline: "For multi-branch and high-volume operations",
    monthly: 200,
    annualMonthly: 167,
    features: [
      "Unlimited orders",
      "Everything in Growth",
      "Multi-branch operations",
      "Cost & margin analytics",
      "Dedicated onboarding",
      "Custom integrations",
      "SLA & account manager",
    ],
  },
];

// TODO(billing): read the tenant's real subscription once billing exists.
const CURRENT_PLAN_ID = "free";

export default function BillingPage() {
  const [period, setPeriod] = useState<Period>("annual");
  const [notice, setNotice] = useState<string | null>(null);
  const savings = Math.round(((35 - 29) / 35) * 100);

  function handleChoose(plan: Plan) {
    if (plan.id === CURRENT_PLAN_ID) return;
    // TODO(billing): replace with a real checkout call once a payment
    // processor is wired up. For now, be honest that nothing happens yet.
    setNotice(
      plan.free
        ? "Downgrading isn't connected yet — contact support to change your plan."
        : `Upgrading to ${plan.name} isn't connected yet — contact support to get started.`
    );
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Billing &amp; Plan</h1>
      <p className="mb-6 text-sm text-slate-500">
        Choose the plan that fits your operation. Prices exclude VAT, billed in USD.
      </p>

      {notice && (
        <Card className="mb-6 flex items-start gap-3 border-amber-200 bg-amber-50 p-4">
          <Info size={18} className="mt-0.5 shrink-0 text-amber-600" />
          <p className="text-sm text-amber-800">{notice}</p>
        </Card>
      )}

      {/* Billing period toggle */}
      <div className="mb-8 inline-flex rounded-full border border-[var(--border)] bg-gray-50 p-1">
        {(["monthly", "annual"] as Period[]).map((p) => {
          const active = period === p;
          return (
            <button
              key={p}
              onClick={() => setPeriod(p)}
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

      {/* Plans: 1 col on mobile, 3 across from lg */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {plans.map((plan) => {
          const isCurrent = plan.id === CURRENT_PLAN_ID;
          const price = period === "annual" ? plan.annualMonthly : plan.monthly;
          return (
            <Card
              key={plan.id}
              className={`flex flex-col p-6 ${plan.recommended ? "border-[var(--primary)]" : ""}`}
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
                    <span className="text-sm text-slate-500">USD</span>
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

              <button
                onClick={() => handleChoose(plan)}
                disabled={isCurrent}
                className={`mt-6 w-full rounded-full py-2.5 text-sm font-medium transition ${
                  isCurrent
                    ? "cursor-default border border-[var(--border)] text-slate-400"
                    : plan.recommended
                    ? "bg-[var(--primary)] text-white hover:opacity-90"
                    : "border border-[var(--border-strong)] text-slate-900 hover:bg-gray-50"
                }`}
              >
                {isCurrent ? "Current plan" : plan.free ? "Downgrade to Free" : `Choose ${plan.name}`}
              </button>
            </Card>
          );
        })}
      </div>

      <p className="mt-6 text-center text-xs text-slate-400">
        Changing plans takes effect immediately. Cancel anytime. Limits apply per organization.
      </p>
    </div>
  );
}