"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, MonitorPlay } from "lucide-react";
import { PlanCard } from "@/components/plan-card";
import { DEMO_AVAILABLE, getSite, startDemo } from "@/lib/api";
import { SALES_EMAIL } from "@/lib/plans";

export default function PublicPlansPage() {
  const router = useRouter();
  const [branches, setBranches] = useState(1);
  // Sign-up is shown unless it was closed in the Stonic Console. While the server can't be
  // reached it stays visible; the sign-up page then explains that Salesman is offline.
  const [signUpOpen, setSignUpOpen] = useState(true);
  useEffect(() => {
    getSite().then((s) => setSignUpOpen(Boolean(s.offline) || s.sign_up_enabled));
  }, []);
  const subject = encodeURIComponent(`Salesman pilot — ${branches} branch${branches === 1 ? "" : "es"}`);

  function seeDemo() {
    startDemo();
    router.push("/overview");
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-4 sm:px-6">
        <Link href="/" className="text-lg font-bold">
          Salesman<span className="text-[var(--primary)]">.</span>
        </Link>
        <nav className="flex items-center gap-2">
          {DEMO_AVAILABLE && (
            <button onClick={seeDemo}
              className="hidden rounded-full px-4 py-1.5 text-sm font-medium text-[var(--primary)] hover:bg-indigo-50 sm:inline-flex">
              See the demo
            </button>
          )}
          <Link href="/login" className="rounded-full border border-[var(--border)] px-4 py-1.5 text-sm font-medium hover:bg-gray-50">
            Sign in
          </Link>
          {signUpOpen && (
            <Link href="/signup" className="rounded-full bg-[var(--primary)] px-4 py-1.5 text-sm font-medium text-white hover:opacity-90">
              Sign up
            </Link>
          )}
        </nav>
      </header>

      <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
        <h1 className="text-center text-3xl font-bold sm:text-4xl">Simple pricing, per branch</h1>
        <p className="mx-auto mt-3 max-w-lg text-center text-slate-500">
          One plan with everything included. A one-time setup for each branch, then a monthly subscription.
        </p>

        {DEMO_AVAILABLE && (
          <div className="mx-auto mt-8 flex max-w-2xl flex-col items-center gap-4 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5 text-center sm:flex-row sm:text-left">
            <MonitorPlay size={28} className="shrink-0 text-[var(--primary)]" />
            <div className="flex-1">
              <div className="font-semibold">See Salesman in action</div>
              <p className="mt-0.5 text-sm text-slate-600">
                Click through the full dashboard of a sample wholesaler: orders, WhatsApp chats, accounts and analytics.
                No sign-up needed.
              </p>
            </div>
            <button onClick={seeDemo}
              className="inline-flex shrink-0 items-center gap-2 rounded-full bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-white hover:opacity-90">
              See the demo <ArrowRight size={16} />
            </button>
          </div>
        )}

        <div className="mt-10">
          <PlanCard
            branches={branches}
            onBranchesChange={setBranches}
            primaryLabel="Talk to us about a pilot"
            primaryHref={`mailto:${SALES_EMAIL}?subject=${subject}`}
            secondaryLabel={signUpOpen ? "Create an account" : undefined}
            secondaryHref={signUpOpen ? "/signup" : undefined}
          />
        </div>
      </div>
    </div>
  );
}