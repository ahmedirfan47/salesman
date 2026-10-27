"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, downloadFile } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { useAllBranchesView, useBranches } from "@/lib/branches";
import {
  AGING_LABELS, AccountRow, AccountSettings, AccountTotals, KIND_LABEL, METHOD_LABEL, Payment, SalesInvoice,
  accountFlags, day, invoiceBadge, money,
} from "@/lib/accounts";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { EInvoicing } from "@/components/einvoicing";
import { edocBadge, FLOW_LABEL } from "@/lib/zatca";
import { Download, Search, ShieldAlert, Wallet } from "lucide-react";

type Tab = "customers" | "invoices" | "payments" | "einvoicing" | "settings";
type Filter = "all" | "owing" | "overdue" | "over_limit" | "on_hold";

const select = "rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";

export default function AccountsPage() {
  const { me, loading } = useMe();
  const allowed = can(me, "view_accounts");
  const manage = can(me, "manage_accounts");
  const [tab, setTab] = useState<Tab>("customers");
  const [rows, setRows] = useState<AccountRow[]>([]);
  const [totals, setTotals] = useState<AccountTotals | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!allowed) return;
    api("/accounts")
      .then((d) => { setRows(d.customers); setTotals(d.totals); })
      .catch((e) => setError(e.message));
  }, [allowed]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!allowed) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">No access</h1>
        <p className="mt-2 text-sm text-slate-500">Customer accounts are visible to owners, admins, salesmen and viewers.</p>
      </Card>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "customers", label: "Customers" },
    { key: "invoices", label: "Invoices" },
    { key: "payments", label: "Payments" },
    { key: "einvoicing", label: "E-invoicing (ZATCA)" },
    ...(manage ? [{ key: "settings" as Tab, label: "Settings" }] : []),
  ];

  return (
    <div>
      <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Wallet size={22} /> Accounts</h1>
      <p className="mb-6 text-sm text-slate-500">What each customer owes, their invoices, payments and credit terms</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-[var(--border)]">
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`-mb-px shrink-0 border-b-2 px-4 py-2 text-sm font-medium ${
              tab === t.key ? "border-[var(--primary)] text-[var(--primary)]" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "customers" && <Customers rows={rows} totals={totals} />}
      {tab === "invoices" && <Invoices rows={rows} setError={setError} />}
      {tab === "payments" && <Payments rows={rows} />}
      {tab === "einvoicing" && <EInvoicing manage={manage} onOpenSettings={() => setTab("settings")} />}
      {tab === "settings" && manage && <Settings />}
    </div>
  );
}

// ---------------------------------------------------------------- customers
function Customers({ rows, totals }: { rows: AccountRow[]; totals: AccountTotals | null }) {
  const { nameOf } = useBranches();
  const allView = useAllBranchesView();
  const [filter, setFilter] = useState<Filter>("owing");
  const [q, setQ] = useState("");

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    return rows
      .filter((r) => {
        if (filter === "owing" && Number(r.balance) <= 0) return false;
        if (filter === "overdue" && Number(r.overdue) <= 0) return false;
        if (filter === "over_limit" && !r.over_limit) return false;
        if (filter === "on_hold" && !r.on_hold) return false;
        if (!term) return true;
        return [r.name, r.company, r.whatsapp_number].some((v) => v?.toLowerCase().includes(term));
      })
      .sort((a, b) => Number(b.overdue) - Number(a.overdue) || Number(b.balance) - Number(a.balance));
  }, [rows, filter, q]);

  if (!totals) return <p className="text-slate-400">Loading…</p>;
  const ccy = totals.currency;
  const agingTotal = AGING_LABELS.reduce((s, a) => s + Number(totals.aging[a.key]), 0);
  const colors = ["bg-emerald-400", "bg-amber-300", "bg-amber-500", "bg-orange-500", "bg-red-600"];

  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Receivable" value={money(ccy, totals.receivable)} hint={`${rows.filter((r) => Number(r.balance) > 0).length} customers owe money`} />
        <Stat label="Overdue" value={money(ccy, totals.overdue)} hint={`${totals.customers_overdue} customers`} tone={Number(totals.overdue) > 0 ? "bad" : undefined} />
        <Stat label="Over credit limit" value={String(totals.customers_over_limit)} hint="New orders need approval" tone={totals.customers_over_limit ? "bad" : undefined} />
        <Stat label="On hold" value={String(totals.customers_on_hold)} hint={Number(totals.unapplied) > 0 ? `${money(ccy, totals.unapplied)} unapplied credit` : "Manual stop on orders"} />
      </div>

      <Card className="mb-6 p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-500">AMOUNT DUE BY AGE</h2>
        {agingTotal > 0 ? (
          <div className="mb-3 flex h-3 overflow-hidden rounded-full bg-gray-100">
            {AGING_LABELS.map((a, i) => {
              const v = Number(totals.aging[a.key]);
              return v > 0 ? <div key={a.key} className={colors[i]} style={{ width: `${(v / agingTotal) * 100}%` }} title={a.label} /> : null;
            })}
          </div>
        ) : (
          <p className="mb-3 text-sm text-slate-400">Nothing owed right now.</p>
        )}
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {AGING_LABELS.map((a, i) => (
            <div key={a.key}>
              <div className="flex items-center gap-1.5 text-xs text-slate-500"><span className={`h-2 w-2 rounded-full ${colors[i]}`} />{a.label}</div>
              <div className="font-semibold tabular-nums">{money(ccy, totals.aging[a.key])}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2">
          {([["owing", "Owes money"], ["overdue", "Overdue"], ["over_limit", "Over limit"], ["on_hold", "On hold"], ["all", "All customers"]] as [Filter, string][]).map(([k, label]) => (
            <button key={k} onClick={() => setFilter(k)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${filter === k ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "border-[var(--border)] bg-white text-slate-600"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="relative sm:w-64">
          <Search size={15} className="absolute left-3 top-2.5 text-slate-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customers" className="pl-9" />
        </div>
      </div>

      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Balance</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Overdue</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Credit limit</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Available</th>
                <th className="px-4 py-3 font-medium">Terms</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.customer_id} className="border-b border-[var(--border)] last:border-0 hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link href={`/accounts/${r.customer_id}`} className="font-medium text-[var(--primary)] hover:underline">{r.name}</Link>
                    <div className="text-xs text-slate-400">
                      {[r.company !== r.name ? r.company : null, allView ? nameOf(r.branch_id) : null].filter(Boolean).join(" · ") || r.whatsapp_number || ""}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums">{money(r.currency, r.balance)}</td>
                  <td className={`whitespace-nowrap px-4 py-3 text-right tabular-nums ${Number(r.overdue) > 0 ? "font-medium text-red-600" : "text-slate-400"}`}>
                    {Number(r.overdue) > 0 ? money(r.currency, r.overdue) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-600">{r.credit_limit !== null ? money(r.currency, r.credit_limit) : "No limit"}</td>
                  <td className={`whitespace-nowrap px-4 py-3 text-right tabular-nums ${r.over_limit ? "text-red-600" : "text-slate-600"}`}>
                    {r.available_credit !== null ? money(r.currency, r.available_credit) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-600">{r.payment_terms_days ? `${r.payment_terms_days} days` : "On delivery"}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {accountFlags(r).map((f) => <span key={f.label} className={`rounded-full px-2 py-0.5 text-xs ${f.className}`}>{f.label}</span>)}
                      {accountFlags(r).length === 0 && <span className="text-xs text-emerald-700">Good standing</span>}
                    </div>
                  </td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">No customers match.</td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- invoices
function Invoices({ rows, setError }: { rows: AccountRow[]; setError: (s: string) => void }) {
  const [status, setStatus] = useState("unpaid");
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<SalesInvoice[] | null>(null);

  useEffect(() => {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    if (kind) p.set("kind", kind);
    setItems(null);
    api(`/accounts/invoices?${p.toString()}`).then(setItems).catch((e) => setError(e.message));
  }, [status, kind, setError]);

  async function pdf(inv: SalesInvoice) {
    try { await downloadFile(`/accounts/invoices/${inv.id}/pdf`, `${inv.number}.pdf`); }
    catch (e) { setError(e instanceof Error ? e.message : "Download failed"); }
  }

  const customerName = (id: string | null) => rows.find((r) => r.customer_id === id)?.name;

  return (
    <>
      <div className="mb-3 flex flex-wrap gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={select}>
          <option value="unpaid">Unpaid</option>
          <option value="overdue">Overdue</option>
          <option value="paid">Paid</option>
          <option value="">All</option>
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={select}>
          <option value="">Invoices and credit notes</option>
          <option value="invoice">Invoices</option>
          <option value="credit_note">Credit notes</option>
          <option value="opening_balance">Opening balances</option>
        </select>
      </div>
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[920px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Number</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Issued</th>
                <th className="px-4 py-3 font-medium">Due</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Total</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Balance</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">ZATCA</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {(items ?? []).map((inv) => {
                const b = invoiceBadge(inv);
                const e = inv.einvoice ? edocBadge(inv.einvoice.status, inv.einvoice.flow) : null;
                const name = customerName(inv.customer_id) ?? inv.buyer?.name ?? "Walk-in";
                return (
                  <tr key={inv.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">{inv.number}<div className="font-sans text-slate-400">{KIND_LABEL[inv.kind]}</div></td>
                    <td className="px-4 py-3">
                      {inv.customer_id ? <Link className="text-[var(--primary)] hover:underline" href={`/accounts/${inv.customer_id}`}>{name}</Link> : name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{day(inv.issue_date)}</td>
                    <td className="px-4 py-3 text-slate-600">{inv.kind === "credit_note" ? "—" : day(inv.due_date)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{money(inv.currency, inv.total)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums">{inv.kind === "credit_note" ? "—" : money(inv.currency, inv.balance_due)}</td>
                    <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 text-xs ${b.className}`}>{b.label}</span></td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {e && inv.einvoice
                        ? <span className={`rounded-full px-2 py-0.5 text-xs ${e.className}`}>{FLOW_LABEL[inv.einvoice.flow]} · {e.label}</span>
                        : <span className="text-xs text-slate-400">—</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      <Button variant="outline" className="px-2 py-1 text-xs" onClick={() => pdf(inv)}><Download size={14} /> PDF</Button>
                    </td>
                  </tr>
                );
              })}
              {items === null && <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
              {items?.length === 0 && <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">No invoices here.</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- payments
function Payments({ rows }: { rows: AccountRow[] }) {
  const [items, setItems] = useState<Payment[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/accounts/payments").then(setItems).catch((e) => setError(e.message)); }, []);
  const customerName = (id: string | null) => rows.find((r) => r.customer_id === id)?.name ?? "Walk-in";

  return (
    <Card className="overflow-hidden">
      {error && <p className="p-4 text-sm text-red-600">{error}</p>}
      <TableScroll>
        <table className="w-full min-w-[760px] text-sm">
          <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Receipt</th>
              <th className="px-4 py-3 font-medium">Date</th>
              <th className="px-4 py-3 font-medium">Customer</th>
              <th className="px-4 py-3 font-medium">Method</th>
              <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Amount</th>
              <th className="whitespace-nowrap px-4 py-3 text-right font-medium">On account</th>
            </tr>
          </thead>
          <tbody>
            {(items ?? []).map((p) => (
              <tr key={p.id} className={`border-b border-[var(--border)] last:border-0 ${p.voided_at ? "text-slate-400" : ""}`}>
                <td className="px-4 py-3 font-mono text-xs">{p.number}{p.voided_at && <div className="font-sans text-red-600">Reversed: {p.void_reason}</div>}</td>
                <td className="whitespace-nowrap px-4 py-3">{day(p.paid_on)}</td>
                <td className="px-4 py-3">
                  {p.customer_id ? <Link className="text-[var(--primary)] hover:underline" href={`/accounts/${p.customer_id}`}>{customerName(p.customer_id)}</Link> : "Walk-in"}
                </td>
                <td className="px-4 py-3">{METHOD_LABEL[p.method]}{p.reference && <span className="text-slate-400"> · {p.reference}</span>}</td>
                <td className={`whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums ${p.voided_at ? "line-through" : ""}`}>{money(p.currency, p.amount)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-500">{Number(p.unallocated) > 0 ? money(p.currency, p.unallocated) : "—"}</td>
              </tr>
            ))}
            {items === null && !error && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
            {items?.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No payments recorded yet.</td></tr>}
          </tbody>
        </table>
      </TableScroll>
    </Card>
  );
}

// ---------------------------------------------------------------- settings
function Settings() {
  const [s, setS] = useState<AccountSettings | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/accounts/settings").then(setS).catch((e) => setError(e.message)); }, []);
  if (!s) return error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-slate-400">Loading…</p>;

  const set = (patch: Partial<AccountSettings>) => setS({ ...s, ...patch });
  async function save() {
    if (!s) return;
    setBusy(true); setError(""); setMsg("");
    try {
      const saved = await api("/accounts/settings", {
        method: "PUT",
        body: JSON.stringify({
          ...s,
          default_credit_limit: s.default_credit_limit === "" || s.default_credit_limit === null ? null : s.default_credit_limit,
        }),
      });
      setS(saved);
      setMsg("Settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-500">INVOICES AND VAT</h2>
        <div className="space-y-3 text-sm">
          <Field label="Issue the invoice when an order is">
            <select value={s.invoice_on} onChange={(e) => set({ invoice_on: e.target.value as AccountSettings["invoice_on"] })} className={`${select} w-full`}>
              <option value="delivered">Delivered</option>
              <option value="confirmed">Confirmed</option>
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="VAT rate (%)"><Input type="number" step="0.01" value={s.vat_rate} onChange={(e) => set({ vat_rate: e.target.value })} /></Field>
            <Field label="Currency"><Input value={s.currency} maxLength={3} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} /></Field>
          </div>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={s.prices_include_vat} onChange={(e) => set({ prices_include_vat: e.target.checked })} />
            Prices in the price list already include VAT
          </label>
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-500">CREDIT CONTROL</h2>
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Default payment terms (days)">
              <Input type="number" min={0} value={s.default_payment_terms_days} onChange={(e) => set({ default_payment_terms_days: Number(e.target.value) })} />
            </Field>
            <Field label="Default credit limit">
              <Input type="number" min={0} placeholder="No limit" value={s.default_credit_limit ?? ""} onChange={(e) => set({ default_credit_limit: e.target.value || null })} />
            </Field>
          </div>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={s.hold_over_limit} onChange={(e) => set({ hold_over_limit: e.target.checked })} />
            Hold orders that take a customer over their credit limit
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={s.hold_when_overdue} onChange={(e) => set({ hold_when_overdue: e.target.checked })} />
            Hold orders while a customer has overdue invoices
          </label>
          {s.hold_when_overdue && (
            <Field label="…after this many days overdue">
              <Input type="number" min={0} value={s.overdue_grace_days} onChange={(e) => set({ overdue_grace_days: Number(e.target.value) })} />
            </Field>
          )}
          <p className="text-xs text-slate-500">Held orders appear under Escalations, where a manager can approve or reject them.</p>
        </div>
      </Card>

      <Card className="p-5 lg:col-span-2">
        <h2 className="mb-4 text-sm font-semibold text-slate-500">SELLER DETAILS ON INVOICES AND STATEMENTS</h2>
        <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <Field label="Business name"><Input value={s.seller_name ?? ""} onChange={(e) => set({ seller_name: e.target.value })} /></Field>
          <Field label="Business name in Arabic"><Input dir="rtl" value={s.seller_name_ar ?? ""} onChange={(e) => set({ seller_name_ar: e.target.value })} /></Field>
          <Field label="VAT registration number"><Input value={s.seller_vat_number ?? ""} maxLength={20} onChange={(e) => set({ seller_vat_number: e.target.value })} /></Field>
          <Field label="Commercial registration (CR) number"><Input value={s.seller_cr_number ?? ""} maxLength={20} onChange={(e) => set({ seller_cr_number: e.target.value })} /></Field>
          <Field label="Address as printed (optional)" className="sm:col-span-2"><Input value={s.seller_address ?? ""} placeholder="Leave empty to print the national address below" onChange={(e) => set({ seller_address: e.target.value })} /></Field>
          <Field label="Footer (bank details, notes)" className="sm:col-span-2">
            <textarea value={s.invoice_footer ?? ""} onChange={(e) => set({ invoice_footer: e.target.value })} rows={3}
              className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]" />
          </Field>
        </div>
      </Card>

      <Card className="p-5 lg:col-span-2">
        <h2 className="mb-1 text-sm font-semibold text-slate-500">NATIONAL ADDRESS (FOR ZATCA E-INVOICES)</h2>
        <p className="mb-4 text-xs text-slate-500">As registered with Saudi Post (SPL). Building number 4 digits, postal code 5 digits.</p>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-6">
          <Field label="Building no." className="col-span-1 sm:col-span-1"><Input value={s.seller_building_number ?? ""} maxLength={4} inputMode="numeric" onChange={(e) => set({ seller_building_number: e.target.value })} /></Field>
          <Field label="Street" className="col-span-1 sm:col-span-3"><Input value={s.seller_street ?? ""} onChange={(e) => set({ seller_street: e.target.value })} /></Field>
          <Field label="District" className="col-span-2 sm:col-span-2"><Input value={s.seller_district ?? ""} onChange={(e) => set({ seller_district: e.target.value })} /></Field>
          <Field label="City" className="col-span-1 sm:col-span-3"><Input value={s.seller_city ?? ""} onChange={(e) => set({ seller_city: e.target.value })} /></Field>
          <Field label="Postal code" className="col-span-1 sm:col-span-3"><Input value={s.seller_postal_code ?? ""} maxLength={5} inputMode="numeric" onChange={(e) => set({ seller_postal_code: e.target.value })} /></Field>
        </div>
      </Card>

      <div className="flex items-center gap-3 lg:col-span-2">
        <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save settings"}</Button>
        {msg && <span className="text-sm text-emerald-700">{msg}</span>}
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </div>
  );
}

function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
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