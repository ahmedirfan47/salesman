"use client";

import { useEffect, useState } from "react";
import { api, downloadFile } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { useBranches } from "@/lib/branches";
import { AccountState, Invoice, KIND_LABEL, Subscription, day, money, statusBadge } from "@/lib/billing";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { TableScroll } from "@/components/table-scroll";
import { PlanCard } from "@/components/plan-card";
import { SALES_EMAIL } from "@/lib/plans";
import { AlertTriangle, Download, Info, Landmark, Lock, ShieldAlert, Copy, Check } from "lucide-react";

type Billing = {
  subscription: Subscription | null;
  account: AccountState;
  active_branches: number;
  unbilled_setup_branches: number;
  invoices: Invoice[];
  pay_to: { name: string; address: string[]; email: string | null; tax_id: string | null; bank_details: string[] };
};

export default function BillingPage() {
  const { me, loading } = useMe();
  const [data, setData] = useState<Billing | null>(null);
  const [error, setError] = useState("");
  const allowed = can(me, "view_billing");

  useEffect(() => {
    if (allowed) api("/billing").then(setData).catch((e) => setError(e.message));
  }, [allowed]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!allowed) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Owners and admins only</h1>
        <p className="mt-2 text-sm text-slate-500">Billing is visible to the business owner and admins.</p>
      </Card>
    );
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Billing &amp; Plan</h1>
      <p className="mb-6 text-sm text-slate-500">Your Salesman subscription and invoices from Stonic.</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {!data && !error && <p className="text-slate-400">Loading…</p>}
      {data && (data.subscription ? <Subscribed data={data} setError={setError} /> : <NotSubscribed />)}
    </div>
  );
}

function NotSubscribed() {
  const { branches: all } = useBranches();
  const active = all.filter((b) => b.is_active).length;
  const [branches, setBranches] = useState(1);
  // start the calculator at the number of branches set up in Salesman
  useEffect(() => { if (active > 0) setBranches(active); }, [active]);
  const subject = encodeURIComponent(`Salesman subscription — ${branches} branch${branches === 1 ? "" : "es"}`);

  return (
    <>
      <div className="mb-6 flex items-start gap-3 rounded-xl border border-indigo-100 bg-indigo-50 p-4">
        <Info size={18} className="mt-0.5 shrink-0 text-[var(--primary)]" />
        <p className="text-sm text-slate-700">
          No subscription is set up for this account yet. Contact the Stonic team to activate it; invoices will then appear here.
        </p>
      </div>
      <PlanCard
        branches={branches}
        onBranchesChange={setBranches}
        primaryLabel="Contact us to activate"
        primaryHref={`mailto:${SALES_EMAIL}?subject=${subject}`}
      />
    </>
  );
}

function Subscribed({ data, setError }: { data: Billing; setError: (s: string) => void }) {
  const sub = data.subscription!;
  const acct = data.account;
  const monthly = Number(sub.monthly_fee_per_branch) * Math.max(data.active_branches, 1);

  async function pdf(inv: Invoice) {
    try { await downloadFile(`/billing/invoices/${inv.id}/pdf`, `${inv.number}.pdf`); }
    catch (e) { setError(e instanceof Error ? e.message : "Download failed"); }
  }

  return (
    <>
      {acct.message && (
        <div className={`mb-6 flex items-start gap-3 rounded-xl border p-4 text-sm ${
          acct.read_only ? "border-red-200 bg-red-50 text-red-900" : "border-amber-200 bg-amber-50 text-amber-900"
        }`}>
          {acct.read_only ? <Lock size={18} className="mt-0.5 shrink-0" /> : <AlertTriangle size={18} className="mt-0.5 shrink-0" />}
          <p>{acct.message}</p>
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Plan" value={sub.status === "active" ? "Active" : sub.status === "paused" ? "Paused" : "Cancelled"}
          hint={`${data.active_branches} active branch${data.active_branches === 1 ? "" : "es"}`} />
        <Stat label="Monthly" value={money(sub.currency, monthly)}
          hint={`${money(sub.currency, sub.monthly_fee_per_branch)} per branch${Number(sub.tax_percent) > 0 ? ` + ${Number(sub.tax_percent)}% VAT` : ""}`} />
        <Stat label="Next invoice" value={sub.status === "active" ? day(sub.next_invoice_on) : "—"}
          hint={`Payment due within ${sub.payment_terms_days} days`} />
        <Stat label="Outstanding" value={money(acct.currency, acct.outstanding)}
          hint={acct.open_invoices ? `${acct.open_invoices} unpaid invoice${acct.open_invoices === 1 ? "" : "s"}` : "Nothing to pay"}
          tone={acct.state === "overdue" || acct.state === "read_only" ? "bad" : undefined} />
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card className="p-5">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><Landmark size={16} /> PAY BY BANK TRANSFER</h2>
          <p className="text-sm font-medium">{data.pay_to.name}</p>
          {data.pay_to.bank_details.length > 0 ? (
            <div className="mt-2 space-y-1">
              {data.pay_to.bank_details.map((line) => <CopyLine key={line} text={line} />)}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">The Stonic team will send you the bank details.</p>
          )}
          <p className="mt-3 text-xs text-slate-500">
            Use the invoice number as the payment reference. Access is restored as soon as Stonic confirms a payment.
            {data.pay_to.email && <> Questions: <a className="text-[var(--primary)] hover:underline" href={`mailto:${data.pay_to.email}`}>{data.pay_to.email}</a></>}
          </p>
        </Card>

        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-500">YOUR PLAN</h2>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <Row label="Setup, per branch" value={money(sub.currency, sub.setup_fee_per_branch)} />
            <Row label="Monthly, per branch" value={money(sub.currency, sub.monthly_fee_per_branch)} />
            <Row label="VAT" value={Number(sub.tax_percent) > 0 ? `${Number(sub.tax_percent)}%` : "Not charged"} />
            <Row label="Payment terms" value={`${sub.payment_terms_days} days`} />
            <Row label="Billed to" value={sub.billing_name ?? "—"} />
            {sub.billing_tax_id && <Row label="Tax ID" value={sub.billing_tax_id} />}
          </dl>
          {data.unbilled_setup_branches > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              {data.unbilled_setup_branches} new branch{data.unbilled_setup_branches === 1 ? "" : "es"} will be invoiced for setup by the Stonic team.
            </p>
          )}
          <p className="mt-3 text-xs text-slate-400">Monthly invoices are issued in advance for the number of active branches on the invoice date.</p>
        </Card>
      </div>

      <h2 className="mb-3 text-sm font-semibold text-slate-500">INVOICES</h2>
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Invoice</th>
                <th className="px-4 py-3 font-medium">For</th>
                <th className="px-4 py-3 font-medium">Issued</th>
                <th className="px-4 py-3 font-medium">Due</th>
                <th className="px-4 py-3 text-right font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {data.invoices.map((inv) => {
                const badge = statusBadge(inv);
                return (
                  <tr key={inv.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3 font-mono text-xs">{inv.number}</td>
                    <td className="px-4 py-3">
                      {KIND_LABEL[inv.kind]}
                      {inv.period_start && <span className="text-slate-400"> · {day(inv.period_start)} – {day(inv.period_end)}</span>}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{day(inv.issued_on)}</td>
                    <td className="px-4 py-3 text-slate-600">{day(inv.due_on)}</td>
                    <td className="px-4 py-3 text-right font-medium tabular-nums">{money(inv.currency, inv.total)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>
                      {inv.status === "paid" && inv.paid_on && <span className="ml-2 text-xs text-slate-400">{day(inv.paid_on)}</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Button variant="outline" className="px-2 py-1 text-xs" onClick={() => pdf(inv)}><Download size={14} /> PDF</Button>
                    </td>
                  </tr>
                );
              })}
              {data.invoices.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">No invoices yet</td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bad" }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-lg font-bold tabular-nums ${tone === "bad" ? "text-red-600" : ""}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-[var(--border)] pb-2 sm:border-0 sm:pb-0">
      <dt className="shrink-0 text-slate-500">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}

function CopyLine({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex items-center justify-between gap-2 rounded-md bg-gray-50 px-3 py-1.5 text-sm">
      <span className="font-mono text-xs">{text}</span>
      <button
        aria-label="Copy"
        className="shrink-0 text-slate-400 hover:text-slate-700"
        onClick={() => { navigator.clipboard?.writeText(text.split(":").slice(1).join(":").trim() || text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {}); }}
      >
        {done ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}