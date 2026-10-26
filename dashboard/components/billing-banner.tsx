"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AlertTriangle, Lock } from "lucide-react";
import { useMe, can } from "@/lib/use-me";

/** Shown on every page when an invoice is overdue, and when the account is read-only. */
export function BillingBanner() {
  const { me } = useMe();
  const pathname = usePathname();
  // the Billing & Plan page shows the same notice itself
  if (pathname.startsWith("/billing")) return null;
  if (!me?.billing_message || (me.billing_state !== "overdue" && me.billing_state !== "read_only")) return null;
  const readOnly = me.billing_state === "read_only";
  const Icon = readOnly ? Lock : AlertTriangle;

  return (
    <div className={`mb-6 flex flex-col gap-2 rounded-xl border px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between ${
      readOnly ? "border-red-200 bg-red-50 text-red-900" : "border-amber-200 bg-amber-50 text-amber-900"
    }`}>
      <div className="flex items-start gap-2">
        <Icon size={16} className="mt-0.5 shrink-0" />
        <span>{me.billing_message}</span>
      </div>
      {can(me, "view_billing") && (
        <Link href="/billing" className="shrink-0 font-medium underline-offset-2 hover:underline">
          View invoices →
        </Link>
      )}
    </div>
  );
}