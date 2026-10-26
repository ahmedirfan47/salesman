"use client";

import { useCallback, useEffect, useState } from "react";
import { api, downloadFile } from "@/lib/api";
import { useMe } from "@/lib/use-me";
import { AccountState, Invoice, KIND_LABEL, STATE_LABEL, Subscription, day, money, statusBadge } from "@/lib/billing";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { Download, Landmark, Plus, RefreshCw, Trash2, X } from "lucide-react";

type TenantRow = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  active_branches: number;
  users: number;
  subscription: Subscription | null;
  unbilled_setup_branches: number;
  account: AccountState;
};
type TenantDetail = TenantRow & { invoices: Invoice[] };

type SubForm = {
  status: string; currency: string; setup_fee_per_branch: string; monthly_fee_per_branch: string;
  tax_percent: string; payment_terms_days: string; grace_days: string; next_invoice_on: string;
  billing_name: string; billing_address: string; billing_tax_id: string; billing_email: string; notes: string;
};

function toForm(t: TenantDetail): SubForm {
  const s = t.subscription;
  return {
    status: s?.status ?? "active",
    currency: s?.currency ?? "USD",
    setup_fee_per_branch: s?.setup_fee_per_branch ?? "11000",
    monthly_fee_per_branch: s?.monthly_fee_per_branch ?? "1050",
    tax_percent: s?.tax_percent ?? "0",
    payment_terms_days: String(s?.payment_terms_days ?? 14),
    grace_days: String(s?.grace_days ?? 14),
    next_invoice_on: s?.next_invoice_on ?? new Date().toISOString().slice(0, 10),
    billing_name: s?.billing_name ?? t.name,
    billing_address: s?.billing_address ?? "",
    billing_tax_id: s?.billing_tax_id ?? "",
    billing_email: s?.billing_email ?? "",
    notes: s?.notes ?? "",
  };
}

export default function PlatformPage() {
  const { me, loading } = useMe();
  const [rows, setRows] = useState<TenantRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const allowed = !!me?.is_platform_admin;

  const load = useCallback(() => {
    api("/platform/tenants").then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { if (allowed) load(); }, [allowed, load]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!allowed) return <p className="text-slate-400">Page not found.</p>;

  async function runBilling() {
    setBusy(true); setError(""); setMsg("");
    try {
      const r = await api("/platform/billing/run", { method: "POST" });
      setMsg(r.issued ? `Issued ${r.issued} monthly invoice${r.issued === 1 ? "" : "s"}.` : "No monthly invoices were due.");
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Landmark size={22} className="text-[var(--primary)]" /> Stonic Console</h1>
          <p className="text-sm text-slate-500">Subscriptions and invoices for every business on Salesman. Only Stonic staff see this page.</p>
        </div>
        <Button variant="outline" onClick={runBilling} disabled={busy}><RefreshCw size={16} /> Issue due invoices</Button>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Business</th>
                <th className="px-4 py-3 font-medium">Branches</th>
                <th className="px-4 py-3 font-medium">Plan</th>
                <th className="px-4 py-3 font-medium">Next invoice</th>
                <th className="px-4 py-3 text-right font-medium">Outstanding</th>
                <th className="px-4 py-3 font-medium">Account</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const st = STATE_LABEL[t.account.state];
                return (
                  <tr key={t.id} onClick={() => setSelected(t.id)}
                    className={`cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-gray-50 ${selected === t.id ? "bg-indigo-50/50" : ""}`}>
                    <td className="px-4 py-3">
                      <div className="font-medium">{t.name}</div>
                      <div className="text-xs text-slate-400">{t.users} user{t.users === 1 ? "" : "s"} · since {day(t.created_at.slice(0, 10))}</div>
                    </td>
                    <td className="px-4 py-3">
                      {t.active_branches}
                      {t.unbilled_setup_branches > 0 && <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">{t.unbilled_setup_branches} setup unbilled</span>}
                    </td>
                    <td className="px-4 py-3">{t.subscription ? <span className="capitalize">{t.subscription.status}</span> : <span className="text-slate-400">None</span>}</td>
                    <td className="px-4 py-3 text-slate-600">{t.subscription?.status === "active" ? day(t.subscription.next_invoice_on) : "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{Number(t.account.outstanding) > 0 ? money(t.account.currency, t.account.outstanding) : "—"}</td>
                    <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 text-xs ${st.className}`}>{st.label}</span></td>
                  </tr>
                );
              })}
              {rows.length === 0 && !error && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No businesses yet</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>

      {selected && <TenantPanel key={selected} tenantId={selected} onChanged={load} onClose={() => setSelected(null)} />}
    </div>
  );
}

function TenantPanel({ tenantId, onChanged, onClose }: { tenantId: string; onChanged: () => void; onClose: () => void }) {
  const [t, setT] = useState<TenantDetail | null>(null);
  const [form, setForm] = useState<SubForm | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d: TenantDetail = await api(`/platform/tenants/${tenantId}`);
      setT(d);
      setForm(toForm(d)); // always show what the server saved (e.g. the next invoice date moves on)
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }, [tenantId]);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setError(""); setMsg("");
    try { await fn(); setMsg(done); await load(); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  if (!t || !form) return <Card className="p-6 text-slate-400">{error || "Loading…"}</Card>;

  function save() {
    const f = form!;
    const body = {
      ...f,
      currency: f.currency.toUpperCase(),
      payment_terms_days: Number(f.payment_terms_days),
      grace_days: Number(f.grace_days),
    };
    act(() => api(`/platform/tenants/${tenantId}/subscription`, { method: "PUT", body: JSON.stringify(body) }),
      t!.subscription ? "Subscription saved." : "Subscription started.");
  }

  const field = (key: keyof SubForm, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="block text-xs font-medium text-slate-500">
      {label}
      <Input className="mt-1" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} {...props} />
    </label>
  );

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t.name}</h2>
          <p className="text-sm text-slate-500">{t.active_branches} active branch{t.active_branches === 1 ? "" : "es"} · {t.users} users</p>
        </div>
        <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-700"><X size={18} /></button>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}
      {t.account.message && <p className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">{t.account.message}</p>}

      <h3 className="mb-3 text-sm font-semibold text-slate-500">SUBSCRIPTION</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-xs font-medium text-slate-500">
          Status
          <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm">
            <option value="active">Active (invoices are issued)</option>
            <option value="paused">Paused (no new invoices)</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        {field("currency", "Currency", { maxLength: 3 })}
        {field("setup_fee_per_branch", "Setup fee per branch", { inputMode: "decimal" })}
        {field("monthly_fee_per_branch", "Monthly fee per branch", { inputMode: "decimal" })}
        {field("tax_percent", "VAT %", { inputMode: "decimal" })}
        {field("payment_terms_days", "Payment terms (days)", { inputMode: "numeric" })}
        {field("grace_days", "Grace before read-only (days)", { inputMode: "numeric" })}
        {field("next_invoice_on", "Next monthly invoice on", { type: "date" })}
        {field("billing_name", "Bill to (legal name)")}
        {field("billing_tax_id", "Customer tax ID / VAT number")}
        {field("billing_email", "Billing email", { type: "email" })}
        {field("billing_address", "Address (use | between lines)")}
      </div>
      <label className="mt-3 block text-xs font-medium text-slate-500">
        Internal notes
        <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2}
          className="mt-1 w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]" />
      </label>
      <p className="mt-2 text-xs text-slate-400">
        Fee changes apply to invoices issued from now on. A next-invoice date in the past issues the missed months at once.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={save} disabled={busy}>{t.subscription ? "Save subscription" : "Start subscription"}</Button>
        {t.subscription && t.unbilled_setup_branches > 0 && (
          <Button variant="outline" disabled={busy}
            onClick={() => act(() => api(`/platform/tenants/${tenantId}/invoices/setup`, { method: "POST", body: "{}" }), "Setup invoice issued.")}>
            Invoice setup for {t.unbilled_setup_branches} branch{t.unbilled_setup_branches === 1 ? "" : "es"}
          </Button>
        )}
        {t.subscription?.status === "active" && (
          <Button variant="outline" disabled={busy}
            onClick={() => act(() => api(`/platform/tenants/${tenantId}/invoices/next`, { method: "POST" }), "Next monthly invoice issued.")}>
            Issue next monthly invoice now
          </Button>
        )}
      </div>

      <CustomInvoice tenantId={tenantId} busy={busy} act={act} />

      <h3 className="mb-3 mt-8 text-sm font-semibold text-slate-500">INVOICES</h3>
      <div className="space-y-3">
        {t.invoices.map((inv) => <InvoiceRow key={inv.id} inv={inv} busy={busy} act={act} />)}
        {t.invoices.length === 0 && <p className="text-sm text-slate-400">No invoices yet.</p>}
      </div>
    </Card>
  );
}

type Act = (fn: () => Promise<unknown>, done: string) => Promise<void>;

function InvoiceRow({ inv, busy, act }: { inv: Invoice; busy: boolean; act: Act }) {
  const [mode, setMode] = useState<"" | "pay" | "void">("");
  const [ref, setRef] = useState("");
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");
  const badge = statusBadge(inv);

  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-sm">
          <span className="font-mono text-xs">{inv.number}</span>
          <span className="ml-2">{KIND_LABEL[inv.kind]}</span>
          <span className="ml-2 font-medium tabular-nums">{money(inv.currency, inv.total)}</span>
          <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>
          <div className="text-xs text-slate-500">
            Issued {day(inv.issued_on)} · due {day(inv.due_on)}
            {inv.period_start && <> · {day(inv.period_start)} – {day(inv.period_end)}</>}
            {inv.status === "paid" && <> · paid {day(inv.paid_on)}{inv.payment_reference ? ` (${inv.payment_reference})` : ""}</>}
            {inv.status === "void" && <> · voided: {inv.void_reason}</>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" className="px-2 py-1 text-xs"
            onClick={() => act(() => downloadFile(`/platform/invoices/${inv.id}/pdf`, `${inv.number}.pdf`), "")}>
            <Download size={14} /> PDF
          </Button>
          {inv.status === "open" && <Button variant="outline" className="px-2 py-1 text-xs" onClick={() => setMode(mode === "pay" ? "" : "pay")}>Mark paid</Button>}
          {inv.status === "open" && <Button variant="ghost" className="px-2 py-1 text-xs text-red-600" onClick={() => setMode(mode === "void" ? "" : "void")}>Void</Button>}
          {inv.status === "paid" && (
            <Button variant="ghost" className="px-2 py-1 text-xs" disabled={busy}
              onClick={() => act(() => api(`/platform/invoices/${inv.id}/reopen`, { method: "POST" }), `${inv.number} reopened.`)}>
              Reopen
            </Button>
          )}
        </div>
      </div>
      {mode === "pay" && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <Input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} className="sm:w-44" />
          <Input placeholder="Bank reference (optional)" value={ref} onChange={(e) => setRef(e.target.value)} />
          <Button disabled={busy} onClick={() => act(
            () => api(`/platform/invoices/${inv.id}/paid`, { method: "POST", body: JSON.stringify({ paid_on: paidOn, reference: ref }) }),
            `${inv.number} marked paid.`,
          )}>Confirm payment</Button>
        </div>
      )}
      {mode === "void" && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <Input placeholder="Reason, e.g. wrong branch count" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="danger" disabled={busy || !reason.trim()} onClick={() => act(
            () => api(`/platform/invoices/${inv.id}/void`, { method: "POST", body: JSON.stringify({ reason }) }),
            `${inv.number} voided.`,
          )}>Void invoice</Button>
        </div>
      )}
    </div>
  );
}

type LineForm = { description: string; quantity: string; unit_amount: string };

function CustomInvoice({ tenantId, busy, act }: { tenantId: string; busy: boolean; act: Act }) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<LineForm[]>([{ description: "", quantity: "1", unit_amount: "" }]);
  const [dueOn, setDueOn] = useState("");
  const [notes, setNotes] = useState("");
  const valid = lines.every((l) => l.description.trim() && Number(l.quantity) > 0 && l.unit_amount !== "" && Number(l.unit_amount) >= 0);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mt-4 inline-flex items-center gap-1 text-sm text-[var(--primary)] hover:underline">
        <Plus size={16} /> Create another invoice (custom lines)
      </button>
    );
  }

  function update(i: number, patch: Partial<LineForm>) {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  return (
    <div className="mt-4 rounded-lg bg-gray-50 p-4">
      <div className="mb-3 text-sm font-semibold">New invoice</div>
      <div className="space-y-2">
        {lines.map((l, i) => (
          <div key={i} className="flex flex-col gap-2 sm:flex-row">
            <Input placeholder="Description" value={l.description} onChange={(e) => update(i, { description: e.target.value })} />
            <Input placeholder="Qty" inputMode="decimal" value={l.quantity} onChange={(e) => update(i, { quantity: e.target.value })} className="sm:w-24" />
            <Input placeholder="Unit price" inputMode="decimal" value={l.unit_amount} onChange={(e) => update(i, { unit_amount: e.target.value })} className="sm:w-36" />
            {lines.length > 1 && (
              <button aria-label="Remove line" onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-2 text-slate-400 hover:text-red-600"><Trash2 size={16} /></button>
            )}
          </div>
        ))}
      </div>
      <button onClick={() => setLines([...lines, { description: "", quantity: "1", unit_amount: "" }])}
        className="mt-2 inline-flex items-center gap-1 text-xs text-[var(--primary)] hover:underline"><Plus size={14} /> Add line</button>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[12rem_1fr]">
        <label className="block text-xs font-medium text-slate-500">
          Due date (optional)
          <Input type="date" className="mt-1" value={dueOn} onChange={(e) => setDueOn(e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          Note printed on the invoice (optional)
          <Input className="mt-1" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      </div>
      <div className="mt-3 flex gap-2">
        <Button disabled={busy || !valid} onClick={async () => {
          await act(() => api(`/platform/tenants/${tenantId}/invoices`, {
            method: "POST",
            body: JSON.stringify({ lines, due_on: dueOn || null, notes: notes || null }),
          }), "Invoice issued.");
          setOpen(false);
          setLines([{ description: "", quantity: "1", unit_amount: "" }]);
          setDueOn(""); setNotes("");
        }}>Issue invoice</Button>
        <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}