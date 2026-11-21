"use client";

import { useEffect, useState } from "react";
import { api, getToken, isDemo } from "@/lib/api";
import { useMe } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { Download, Eraser, Lock, ShieldAlert, ShieldCheck } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Customer = { id: string; name: string; company: string | null; whatsapp_number: string | null; is_active: boolean };
type Request = { id: string; kind: string; subject_id: string | null; requested_by: string | null; detail: Record<string, unknown>; created_at: string };

const KIND: Record<string, string> = { export: "Full export", erase_customer: "Customer erased", retention: "Old messages deleted" };
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function PrivacyPage() {
  const { me, loading } = useMe();
  const isAdmin = me?.role === "owner" || me?.role === "admin" || me?.role === "demo";
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [log, setLog] = useState<Request[] | null>(null);
  const [days, setDays] = useState("");
  const [target, setTarget] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  function load() {
    api("/privacy/requests").then(setLog).catch((e) => setError(e.message));
    api("/customers").then(setCustomers).catch(() => setCustomers([]));
  }
  useEffect(() => {
    if (!isAdmin) return;
    load();
    // the saved period, unless the owner has already started typing a new one
    api("/agent/settings")
      .then((s) => setDays((d) => d || (s.message_retention_days ? String(s.message_retention_days) : "")))
      .catch(() => {});
  }, [isAdmin]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!isAdmin) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">No access</h1>
        <p className="mt-2 text-sm text-slate-500">Only owners and admins can export or erase data.</p>
      </Card>
    );
  }

  async function exportAll() {
    if (isDemo()) { setError("Downloads aren't available in the demo."); return; }
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${API_BASE}/api/v1/privacy/export`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!r.ok) throw new Error(`Export failed (${r.status})`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob());
      a.download = `salesman-export-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveRetention() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api("/agent/settings", { method: "PUT", body: JSON.stringify({ message_retention_days: Number(days) || 0 }) });
      setMsg(Number(days) ? `WhatsApp messages older than ${days} days will be deleted every hour.` : "Messages are kept.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const chosen = customers.find((c) => c.id === target);
  const label = chosen ? chosen.company || chosen.name : "";

  async function erase() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r = await api(`/privacy/customers/${target}/erase`, { method: "POST", body: JSON.stringify({ confirm: true }) });
      setMsg(`${label} erased: ${r.orders} order(s) anonymised, ${r.messages_deleted} message(s) deleted; ${r.invoices_kept} tax invoice(s) kept as the law requires.`);
      setTarget("");
      setTyped("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><ShieldCheck size={22} /> Data protection</h1>
        <p className="text-sm text-slate-500">
          Tools for the Saudi Personal Data Protection Law (PDPL): export everything, erase a customer on request, and keep
          WhatsApp messages only as long as you need them. Every action is recorded below.
        </p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {msg && <p className="text-sm text-emerald-700">{msg}</p>}

      <Card className="p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-500"><Download size={16} /> EXPORT ALL DATA</h2>
        <p className="mb-3 text-sm text-slate-500">
          A ZIP of JSON files: customers, products, prices, orders, invoices, payments, conversations and messages. Passwords,
          WhatsApp tokens and ERP keys are never included.
        </p>
        <Button variant="outline" disabled={busy} onClick={exportAll}><Download size={16} /> Download export</Button>
      </Card>

      <Card className="p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-500"><Lock size={16} /> KEEP WHATSAPP MESSAGES FOR</h2>
        <p className="mb-3 text-sm text-slate-500">Older message text is deleted automatically. Orders, invoices and payments are kept. Empty or 0 keeps messages.</p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs font-medium text-slate-500">Days
            <Input className="mt-1 w-32" type="number" min={0} max={3650} value={days} onChange={(e) => setDays(e.target.value)} />
          </label>
          <Button disabled={busy} onClick={saveRetention}>Save</Button>
        </div>
      </Card>

      <Card className="border-red-100 p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-red-700"><Eraser size={16} /> ERASE A CUSTOMER</h2>
        <p className="mb-3 text-sm text-slate-500">
          For a customer who asks to be forgotten. Their name, number, company, address and identifiers are removed from the
          customer record, their orders and conversations; their WhatsApp messages and the words the AI learned from them are
          deleted. Issued tax invoices stay as they are, as VAT law requires. The balance must be zero first. This can&apos;t be undone.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-slate-500">Customer
            <select className="mt-1 w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm" value={target}
              onChange={(e) => { setTarget(e.target.value); setTyped(""); }}>
              <option value="">Choose…</option>
              {customers.filter((c) => c.whatsapp_number || c.is_active).map((c) => (
                <option key={c.id} value={c.id}>{c.company || c.name}{c.whatsapp_number ? ` · ${c.whatsapp_number}` : ""}</option>
              ))}
            </select>
          </label>
          {chosen && (
            <label className="text-xs font-medium text-slate-500">Type <span className="font-semibold text-slate-700">{label}</span> to confirm
              <Input className="mt-1" value={typed} onChange={(e) => setTyped(e.target.value)} />
            </label>
          )}
        </div>
        <Button variant="danger" className="mt-3" disabled={busy || !chosen || typed.trim() !== label} onClick={erase}>
          <Eraser size={16} /> Erase customer
        </Button>
      </Card>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-slate-500">RECORD OF REQUESTS</h2>
        <Card className="overflow-hidden">
          <TableScroll>
            <table className="w-full min-w-[560px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr><th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3 font-medium">What</th>
                  <th className="px-4 py-3 font-medium">By</th><th className="px-4 py-3 font-medium">Details</th></tr>
              </thead>
              <tbody>
                {(log ?? []).map((r) => (
                  <tr key={r.id} className="border-b border-[var(--border)] last:border-0 align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{when(r.created_at)}</td>
                    <td className="px-4 py-3 font-medium">{KIND[r.kind] ?? r.kind}</td>
                    <td className="px-4 py-3 text-slate-600">{r.requested_by ?? "Automatic"}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {Object.entries(r.detail).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? Object.entries(v as Record<string, number>).map(([a, b]) => `${a} ${b}`).join(", ") : v}`).join(" · ")}
                    </td>
                  </tr>
                ))}
                {log?.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Nothing yet.</td></tr>}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      </section>
    </div>
  );
}
