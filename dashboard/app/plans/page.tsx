"use client";

import { useState } from "react";
import Link from "next/link";
import { PlanCard } from "@/components/plan-card";
import { SALES_EMAIL } from "@/lib/plans";

export default function PublicPlansPage() {
  const [branches, setBranches] = useState(1);
  const subject = encodeURIComponent(`Salesman pilot — ${branches} branch${branches === 1 ? "" : "es"}`);

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

      <div className="mx-auto max-w-4xl px-6 py-12">
        <h1 className="text-center text-3xl font-bold sm:text-4xl">Simple pricing, per branch</h1>
        <p className="mx-auto mt-3 max-w-lg text-center text-slate-500">
          One plan with everything included. A one-time setup for each branch, then a monthly subscription.
        </p>

        <div className="mt-10">
          <PlanCard
            branches={branches}
            onBranchesChange={setBranches}
            primaryLabel="Talk to us about a pilot"
            primaryHref={`mailto:${SALES_EMAIL}?subject=${subject}`}
            secondaryLabel="Create an account"
            secondaryHref="/signup"
          />
        </div>
      </div>
    </div>
  );
}