"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import {
  AGING_LABELS, AccountRow, KIND_LABEL, METHOD_LABEL, Payment, SalesInvoice, Statement, TaxDetails,
  accountFlags, day, invoiceBadge, money, today,
} from "@/lib/accounts";
import { FLOW_LABEL, edocBadge } from "@/lib/zatca";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { ArrowLeft, Banknote, Download, FileText, Landmark, Scale, SlidersHorizontal, Undo2 } from "lucide-react";

type Detail = {
  account: AccountRow;
  vat_number: string | null;
  tax: TaxDetails;
  own_credit_limit: string | null;
  own_payment_terms_days: number | null;
  invoices: SalesInvoice[];
  payments: Payment[];
};
type Panel = "" | "payment" | "terms" | "tax" | "opening";

const select = "rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function CustomerAccountPage() {
  const { id } = useParams<{ id: string }>();
  const { me } = useMe();
  const manage = can(me, "manage_accounts");
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [panel, setPanel] = useState<Panel>("");
  const [version, setVersion] = useState(0);

  const load = useCallback(async () => {
    try {
      setData(await api(`/accounts/customers/${id}`));
      setVersion((v) => v + 1);  // the statement reloads too
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function done(text: string) {
    setMsg(text);
    setPanel("");
    await load();
  }

  if (!data) {
    return (
      <div>
        <Link href="/accounts" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft size={16} /> Accounts</Link>
        {error ? <p className="text-red-600">{error}</p> : <p className="text-slate-400">Loading…</p>}
      </div>
    );
  }

  const a = data.account;
  const ccy = a.currency;

  return (
    <div className="max-w-5xl">
      <Link href="/accounts" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft size={16} /> Accounts
      </Link>

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">{a.name}</h1>
          <p className="text-sm text-slate-500">
            {[a.company !== a.name ? a.company : null, a.whatsapp_number, data.vat_number ? `VAT ${data.vat_number}` : null,
              data.tax.cr_number ? `CR ${data.tax.cr_number}` : null].filter(Boolean).join(" · ")}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            {data.tax.vat_number || data.tax.cr_number
              ? "Business customer: standard (B2B) e-invoices, cleared by ZATCA"
              : "Simplified (B2C) e-invoices. Add a VAT or CR number for standard ones."}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {accountFlags(a).map((f) => <span key={f.label} className={`rounded-full px-2 py-0.5 text-xs ${f.className}`}>{f.label}</span>)}
            {accountFlags(a).length === 0 && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Good standing</span>}
          </div>
        </div>
        {manage && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setPanel(panel === "payment" ? "" : "payment")}><Banknote size={16} /> Record payment</Button>
            <Button variant="outline" onClick={() => setPanel(panel === "terms" ? "" : "terms")}><SlidersHorizontal size={16} /> Credit terms</Button>
            <Button variant="outline" onClick={() => setPanel(panel === "tax" ? "" : "tax")}><Landmark size={16} /> Tax and address</Button>
            <Button variant="outline" onClick={() => setPanel(panel === "opening" ? "" : "opening")}><Scale size={16} /> Opening balance</Button>
          </div>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      {panel === "payment" && <PaymentForm detail={data} onDone={done} onCancel={() => setPanel("")} />}
      {panel === "terms" && <TermsForm detail={data} onDone={done} onCancel={() => setPanel("")} />}
      {panel === "tax" && <TaxForm customerId={id} tax={data.tax} onDone={done} onCancel={() => setPanel("")} />}
      {panel === "opening" && <OpeningForm customerId={id} ccy={ccy} onDone={done} onCancel={() => setPanel("")} />}

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Balance" value={money(ccy, a.balance)} hint={Number(a.uninvoiced) > 0 ? `+ ${money(ccy, a.uninvoiced)} not yet invoiced` : `${a.open_invoices} unpaid invoice${a.open_invoices === 1 ? "" : "s"}`} />
        <Stat label="Overdue" value={money(ccy, a.overdue)} hint={a.oldest_overdue_days ? `Oldest ${a.oldest_overdue_days} days late` : "Nothing late"} tone={Number(a.overdue) > 0 ? "bad" : undefined} />
        <Stat label="Credit limit" value={a.credit_limit !== null ? money(ccy, a.credit_limit) : "No limit"}
          hint={a.available_credit !== null ? `${money(ccy, a.available_credit)} available` : data.own_credit_limit === null ? "Business default" : undefined}
          tone={a.over_limit ? "bad" : undefined} />
        <Stat label="Payment terms" value={a.payment_terms_days ? `${a.payment_terms_days} days` : "On delivery"}
          hint={data.own_payment_terms_days === null ? "Business default" : "Set for this customer"} />
      </div>

      <Card className="mb-6 grid grid-cols-2 gap-3 p-4 text-sm sm:grid-cols-5">
        {AGING_LABELS.map((x) => (
          <div key={x.key}>
            <div className="text-xs text-slate-500">{x.label}</div>
            <div className={`font-semibold tabular-nums ${x.key !== "current" && Number(a.aging[x.key]) > 0 ? "text-red-600" : ""}`}>{money(ccy, a.aging[x.key])}</div>
          </div>
        ))}
      </Card>

      <StatementCard customerId={id} name={a.name} version={version} setError={setError} />
      <InvoicesCard invoices={data.invoices} manage={manage} onDone={done} setError={setError} />
      <PaymentsCard payments={data.payments} manage={manage} onDone={done} setError={setError} />
    </div>
  );
}

// ---------------------------------------------------------------- forms
function PaymentForm({ detail, onDone, onCancel }: { detail: Detail; onDone: (m: string) => void; onCancel: () => void }) {
  const open = detail.invoices.filter((i) => i.kind !== "credit_note" && Number(i.balance_due) > 0);
  const [f, setF] = useState({ amount: "", method: "bank_transfer", reference: "", paid_on: today(), invoice_id: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true); setError("");
    try {
      const p: Payment = await api("/accounts/payments", {
        method: "POST",
        body: JSON.stringify({
          customer_id: detail.account.customer_id, invoice_id: f.invoice_id || null, amount: f.amount,
          method: f.method, reference: f.reference || null, paid_on: f.paid_on || null, notes: f.notes || null,
        }),
      });
      onDone(`Payment ${p.number} recorded${Number(p.unallocated) > 0 ? `; ${money(p.currency, p.unallocated)} stays on account` : ""}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <h2 className="mb-4 text-sm font-semibold text-slate-500">RECORD A PAYMENT</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Input type="number" min={0} step="0.01" placeholder={`Amount (${detail.account.currency})`} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
        <select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })} className={select}>
          {Object.entries(METHOD_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <Input type="date" max={today()} value={f.paid_on} onChange={(e) => setF({ ...f, paid_on: e.target.value })} />
        <Input placeholder="Reference (transfer no., cheque no.)" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} />
        <select value={f.invoice_id} onChange={(e) => setF({ ...f, invoice_id: e.target.value })} className={`${select} sm:col-span-2`}>
          <option value="">Pay the oldest invoices first</option>
          {open.map((i) => <option key={i.id} value={i.id}>{i.number} · {money(i.currency, i.balance_due)} due {day(i.due_date)}</option>)}
        </select>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={save} disabled={busy || !(Number(f.amount) > 0)}>{busy ? "Saving…" : "Record payment"}</Button>
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

function TermsForm({ detail, onDone, onCancel }: { detail: Detail; onDone: (m: string) => void; onCancel: () => void }) {
  const [limit, setLimit] = useState(detail.own_credit_limit ?? "");
  const [terms, setTerms] = useState(detail.own_payment_terms_days === null ? "" : String(detail.own_payment_terms_days));
  const [onHold, setOnHold] = useState(detail.account.on_hold);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true); setError("");
    try {
      await api(`/accounts/customers/${detail.account.customer_id}/credit`, {
        method: "PATCH",
        body: JSON.stringify({
          credit_limit: limit === "" ? null : limit,
          payment_terms_days: terms === "" ? null : Number(terms),
          on_hold: onHold,
        }),
      });
      onDone("Credit terms saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <h2 className="mb-4 text-sm font-semibold text-slate-500">CREDIT TERMS</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-slate-500">Credit limit
          <Input type="number" min={0} className="mt-1" placeholder="Business default" value={limit} onChange={(e) => setLimit(e.target.value)} />
        </label>
        <label className="text-xs font-medium text-slate-500">Payment terms (days)
          <Input type="number" min={0} className="mt-1" placeholder="Business default" value={terms} onChange={(e) => setTerms(e.target.value)} />
        </label>
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={onHold} onChange={(e) => setOnHold(e.target.checked)} />
        Put the account on hold (every new order waits for approval)
      </label>
      <p className="mt-2 text-xs text-slate-500">Leave the limit or terms empty to use the business defaults from Accounts › Settings.</p>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

function TaxForm({ customerId, tax, onDone, onCancel }: {
  customerId: string; tax: TaxDetails; onDone: (m: string) => void; onCancel: () => void;
}) {
  const [f, setF] = useState({
    vat_number: tax.vat_number ?? "", cr_number: tax.cr_number ?? "", building_number: tax.building_number ?? "",
    street: tax.street ?? "", district: tax.district ?? "", city: tax.city ?? "", postal_code: tax.postal_code ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = (key: keyof typeof f, label: string, extra: Record<string, unknown> = {}, span = "") => (
    <label className={`text-xs font-medium text-slate-500 ${span}`}>{label}
      <Input className="mt-1" value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })} {...extra} />
    </label>
  );

  async function save() {
    setBusy(true); setError("");
    try {
      await api(`/accounts/customers/${customerId}/tax-details`, { method: "PATCH", body: JSON.stringify(f) });
      onDone("Tax details saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <h2 className="mb-1 text-sm font-semibold text-slate-500">TAX REGISTRATION AND NATIONAL ADDRESS</h2>
      <p className="mb-4 text-xs text-slate-500">
        With a VAT or CR number, this customer gets standard (B2B) e-invoices, which ZATCA clears and which need the full national address.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
        {field("vat_number", "VAT number", { maxLength: 15, inputMode: "numeric", placeholder: "3xxxxxxxxxxxxx3" }, "col-span-2 sm:col-span-3")}
        {field("cr_number", "CR number", { maxLength: 10, inputMode: "numeric" }, "col-span-2 sm:col-span-3")}
        {field("building_number", "Building no.", { maxLength: 4, inputMode: "numeric" }, "col-span-1")}
        {field("street", "Street", {}, "col-span-1 sm:col-span-3")}
        {field("district", "District", {}, "col-span-2")}
        {field("city", "City", {}, "col-span-1 sm:col-span-3")}
        {field("postal_code", "Postal code", { maxLength: 5, inputMode: "numeric" }, "col-span-1 sm:col-span-3")}
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

function OpeningForm({ customerId, ccy, onDone, onCancel }: { customerId: string; ccy: string; onDone: (m: string) => void; onCancel: () => void }) {
  const [f, setF] = useState({ amount: "", as_of: today(), due_date: today(), note: "Balance carried over" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true); setError("");
    try {
      const inv: SalesInvoice = await api(`/accounts/customers/${customerId}/opening-balance`, {
        method: "POST", body: JSON.stringify({ ...f, note: f.note || null }),
      });
      onDone(`Opening balance ${inv.number} added.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <h2 className="mb-1 text-sm font-semibold text-slate-500">OPENING BALANCE</h2>
      <p className="mb-4 text-xs text-slate-500">What this customer already owed before you moved to Salesman. Record money you owe them as a payment instead.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <Input type="number" min={0} step="0.01" placeholder={`Amount (${ccy})`} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
        <label className="text-xs text-slate-500">As of<Input type="date" className="mt-1" value={f.as_of} onChange={(e) => setF({ ...f, as_of: e.target.value })} /></label>
        <label className="text-xs text-slate-500">Due on<Input type="date" className="mt-1" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></label>
        <Input placeholder="Note" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={save} disabled={busy || !(Number(f.amount) > 0)}>{busy ? "Saving…" : "Add opening balance"}</Button>
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- statement
function StatementCard({ customerId, name, version, setError }: {
  customerId: string; name: string; version: number; setError: (s: string) => void;
}) {
  const [start, setStart] = useState(daysAgo(90));
  const [end, setEnd] = useState(today());
  const [st, setSt] = useState<Statement | null>(null);

  useEffect(() => {
    api(`/accounts/customers/${customerId}/statement?start=${start}&end=${end}`)
      .then(setSt)
      .catch((e) => setError(e.message));
  }, [customerId, start, end, version, setError]);

  async function pdf() {
    try { await downloadFile(`/accounts/customers/${customerId}/statement/pdf?start=${start}&end=${end}`, `Statement ${name} ${end}.pdf`); }
    catch (e) { setError(e instanceof Error ? e.message : "Download failed"); }
  }

  return (
    <>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-sm font-semibold text-slate-500">STATEMENT</h2>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-slate-500">From<Input type="date" className="mt-1" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label className="text-xs text-slate-500">To<Input type="date" className="mt-1" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <Button variant="outline" onClick={pdf}><Download size={16} /> PDF</Button>
        </div>
      </div>
      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Document</th>
                <th className="px-4 py-3 font-medium">Description</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Debit</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Credit</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Balance</th>
              </tr>
            </thead>
            <tbody>
              {st && (
                <tr className="border-b border-[var(--border)] text-slate-500">
                  <td className="whitespace-nowrap px-4 py-2">{day(st.start)}</td>
                  <td className="px-4 py-2" colSpan={4}>Opening balance</td>
                  <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">{money(st.currency, st.opening_balance)}</td>
                </tr>
              )}
              {st?.lines.map((l, i) => (
                <tr key={i} className="border-b border-[var(--border)] last:border-0">
                  <td className="whitespace-nowrap px-4 py-2">{day(l.date)}</td>
                  <td className="px-4 py-2 font-mono text-xs">{l.document_number}</td>
                  <td className="px-4 py-2 text-slate-600">{l.description}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">{Number(l.debit) ? money(st.currency, l.debit) : ""}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">{Number(l.credit) ? money(st.currency, l.credit) : ""}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-right font-medium tabular-nums">{money(st.currency, l.balance)}</td>
                </tr>
              ))}
              {st && st.lines.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-400">No activity in this period.</td></tr>}
              {!st && <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-400">Loading…</td></tr>}
            </tbody>
            {st && (
              <tfoot>
                <tr className="bg-gray-50 font-semibold">
                  <td className="px-4 py-3" colSpan={5}>Closing balance</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{money(st.currency, st.closing_balance)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </TableScroll>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- invoices and payments
function InvoicesCard({ invoices, manage, onDone, setError }: {
  invoices: SalesInvoice[]; manage: boolean; onDone: (m: string) => void; setError: (s: string) => void;
}) {
  const [crediting, setCrediting] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function pdf(inv: SalesInvoice) {
    try { await downloadFile(`/accounts/invoices/${inv.id}/pdf`, `${inv.number}.pdf`); }
    catch (e) { setError(e instanceof Error ? e.message : "Download failed"); }
  }
  async function credit(inv: SalesInvoice) {
    setBusy(true); setError("");
    try {
      const note: SalesInvoice = await api(`/accounts/invoices/${inv.id}/credit-note`, {
        method: "POST", body: JSON.stringify({ amount: amount || null, reason }),
      });
      setCrediting(null); setAmount(""); setReason("");
      onDone(`Credit note ${note.number} issued for ${money(note.currency, note.total)}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><FileText size={16} /> INVOICES AND CREDIT NOTES</h2>
      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Number</th>
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
              {invoices.map((inv) => {
                const b = invoiceBadge(inv);
                const e = inv.einvoice ? edocBadge(inv.einvoice.status, inv.einvoice.flow) : null;
                const creditable = inv.kind !== "credit_note" && Number(inv.total) - Number(inv.amount_credited) > 0;
                return (
                  <FragmentRows key={inv.id}>
                    <tr className="border-b border-[var(--border)]">
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">{inv.number}
                        <div className="font-sans text-slate-400">{KIND_LABEL[inv.kind]}{inv.reason ? ` · ${inv.reason}` : ""}</div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">{day(inv.issue_date)}</td>
                      <td className="px-4 py-3">{inv.kind === "credit_note" ? "—" : day(inv.due_date)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{money(inv.currency, inv.total)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums">{inv.kind === "credit_note" ? "—" : money(inv.currency, inv.balance_due)}</td>
                      <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 text-xs ${b.className}`}>{b.label}</span></td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {e && inv.einvoice
                          ? <span className={`rounded-full px-2 py-0.5 text-xs ${e.className}`}>{FLOW_LABEL[inv.einvoice.flow]} · {e.label}</span>
                          : <span className="text-xs text-slate-400">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          {manage && creditable && (
                            <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setCrediting(crediting === inv.id ? null : inv.id)}>
                              <Undo2 size={14} /> Credit
                            </Button>
                          )}
                          <Button variant="outline" className="px-2 py-1 text-xs" onClick={() => pdf(inv)}><Download size={14} /> PDF</Button>
                        </div>
                      </td>
                    </tr>
                    {crediting === inv.id && (
                      <tr className="border-b border-[var(--border)] bg-violet-50/50">
                        <td colSpan={8} className="px-4 py-3">
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                            <Input type="number" min={0} step="0.01" className="sm:w-48"
                              placeholder={`Amount incl. VAT (all: ${money(inv.currency, Number(inv.total) - Number(inv.amount_credited))})`}
                              value={amount} onChange={(e) => setAmount(e.target.value)} />
                            <Input placeholder="Reason, e.g. 3 boxes returned damaged" value={reason} onChange={(e) => setReason(e.target.value)} />
                            <Button disabled={busy || !reason.trim()} onClick={() => credit(inv)}>{busy ? "Issuing…" : "Issue credit note"}</Button>
                            <Button variant="outline" onClick={() => setCrediting(null)}>Cancel</Button>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">Leave the amount empty to credit everything still creditable. Invoices are never deleted; a credit note corrects them.</p>
                        </td>
                      </tr>
                    )}
                  </FragmentRows>
                );
              })}
              {invoices.length === 0 && <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">No invoices yet.</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </>
  );
}

function PaymentsCard({ payments, manage, onDone, setError }: {
  payments: Payment[]; manage: boolean; onDone: (m: string) => void; setError: (s: string) => void;
}) {
  const [reversing, setReversing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function reverse(p: Payment) {
    setBusy(true); setError("");
    try {
      await api(`/accounts/payments/${p.id}/void`, { method: "POST", body: JSON.stringify({ reason }) });
      setReversing(null); setReason("");
      onDone(`Payment ${p.number} reversed; the invoices it paid are open again.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><Banknote size={16} /> PAYMENTS</h2>
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Receipt</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Method</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Amount</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">On account</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <FragmentRows key={p.id}>
                  <tr className={`border-b border-[var(--border)] ${p.voided_at ? "text-slate-400" : ""}`}>
                    <td className="px-4 py-3 font-mono text-xs">{p.number}{p.voided_at && <div className="font-sans text-red-600">Reversed: {p.void_reason}</div>}</td>
                    <td className="whitespace-nowrap px-4 py-3">{day(p.paid_on)}</td>
                    <td className="px-4 py-3">{METHOD_LABEL[p.method]}{p.reference && <span className="text-slate-400"> · {p.reference}</span>}</td>
                    <td className={`whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums ${p.voided_at ? "line-through" : ""}`}>{money(p.currency, p.amount)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-500">{Number(p.unallocated) > 0 ? money(p.currency, p.unallocated) : "—"}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {manage && !p.voided_at && (
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setReversing(reversing === p.id ? null : p.id)}>Reverse</Button>
                      )}
                    </td>
                  </tr>
                  {reversing === p.id && (
                    <tr className="border-b border-[var(--border)] bg-red-50/60">
                      <td colSpan={6} className="px-4 py-3">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                          <Input placeholder="Why? e.g. cheque bounced" value={reason} onChange={(e) => setReason(e.target.value)} />
                          <Button variant="danger" disabled={busy || !reason.trim()} onClick={() => reverse(p)}>{busy ? "Reversing…" : "Reverse payment"}</Button>
                          <Button variant="outline" onClick={() => setReversing(null)}>Cancel</Button>
                        </div>
                      </td>
                    </tr>
                  )}
                </FragmentRows>
              ))}
              {payments.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No payments recorded yet.</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </>
  );
}

function FragmentRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
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