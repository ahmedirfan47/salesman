"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { PlanCard } from "@/components/plan-card";
import { SALES_EMAIL } from "@/lib/plans";

export default function BillingPage() {
  const [branches, setBranches] = useState(1);
  const subject = encodeURIComponent(`Salesman subscription — ${branches} branch${branches === 1 ? "" : "es"}`);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Billing &amp; Plan</h1>
      <p className="mb-6 text-sm text-slate-500">Salesman is priced per branch. Prices in USD, excluding VAT.</p>

      {/* TODO(billing): show the tenant's real subscription and invoices once billing is wired. */}
      <div className="mb-6 flex items-start gap-3 rounded-xl border border-indigo-100 bg-indigo-50 p-4">
        <Info size={18} className="mt-0.5 shrink-0 text-[var(--primary)]" />
        <p className="text-sm text-slate-700">
          Online billing isn&apos;t connected yet. To activate or add branches, contact the Stonic team and we&apos;ll set it up for you.
        </p>
      </div>

      <PlanCard
        branches={branches}
        onBranchesChange={setBranches}
        primaryLabel="Contact us to activate"
        primaryHref={`mailto:${SALES_EMAIL}?subject=${subject}`}
      />
    </div>
  );
}