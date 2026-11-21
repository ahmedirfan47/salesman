"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { BellRing, Send } from "lucide-react";

type Item = { sku: string; name: string; quantity: number };
type Nudge = {
  id: string; customer: string; status: string; due_on: string; typical_days: number; suggested: Item[]; error: string | null;
  sent_at: string | null; created_at: string; converted_order: string | null; converted_amount: string | null; currency: string | null;
};
type Upcoming = { customer_id: string; customer: string; last_order_on: string; typical_days: number; due_on: string; days_late: number };
type Overview = {
  enabled: boolean; factor: string; min_orders: number; template: string | null; template_hint: { en: string; ar: string };
  stats: { sent: number; converted: number; conversion_rate: number | null; converted_value: string };
  upcoming: Upcoming[]; nudges: Nudge[];
};

const STATUS: Record<string, string> = {
  queued: "bg-blue-50 text-blue-700", sent: "bg-emerald-50 text-emerald-700", failed: "bg-red-50 text-red-700",
  skipped: "bg-gray-100 text-slate-600",
};
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function ReordersPage() {
  const { me } = useMe();
  const manage = can(me, "manage_pricing");
  const [o, setO] = useState<Overview | null>(null);
  const [s, setS] = useState({ enabled: false, factor: "1.25", min_orders: "3", template: "" });
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api("/reorder").then((r: Overview) => {
      setO(r);
      setS({ enabled: r.enabled, factor: String(r.factor), min_orders: String(r.min_orders), template: r.template ?? "" });
    }).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function save() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api("/agent/settings", {
        method: "PUT",
        body: JSON.stringify({ reorder_enabled: s.enabled, reorder_factor: Number(s.factor), reorder_min_orders: Number(s.min_orders),
          reorder_template: s.template.trim() }),
      });
      setMsg("Saved.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r = await api("/reorder/run", { method: "POST" });
      setMsg(r.queued ? `${r.queued} message(s) queued.` : "Nobody is due right now.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><BellRing size={22} /> Reorder reminders</h1>
      <p className="mb-6 text-sm text-slate-500">
        Salesman learns how often each customer orders. When one is later than usual, it sends one WhatsApp message offering their
        last order again. A reply goes to the AI like any order, so nothing is ordered without the customer confirming.
      </p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}
      {!o && !error && <p className="text-slate-400">Loading…</p>}

      {o && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Messages sent" value={String(o.stats.sent)} />
            <Kpi label="Ordered within 7 days" value={String(o.stats.converted)} />
            <Kpi label="Conversion" value={o.stats.conversion_rate === null ? "—" : `${o.stats.conversion_rate}%`} />
            <Kpi label="Orders brought back" value={Number(o.stats.converted_value).toLocaleString("en-US", { maximumFractionDigits: 0 })} />
          </div>

          <Card className="p-5">
            <h2 className="mb-3 text-sm font-semibold text-slate-500">SETTINGS</h2>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" disabled={!manage} checked={s.enabled} onChange={(e) => setS({ ...s, enabled: e.target.checked })} />
              <span className="font-medium">Send reorder reminders</span>
            </label>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="text-xs font-medium text-slate-500">Remind when this late (× their usual gap)
                <Input className="mt-1" type="number" min={1} max={5} step="0.05" disabled={!manage} value={s.factor}
                  onChange={(e) => setS({ ...s, factor: e.target.value })} />
              </label>
              <label className="text-xs font-medium text-slate-500">Only customers with at least this many orders
                <Input className="mt-1" type="number" min={2} max={50} disabled={!manage} value={s.min_orders}
                  onChange={(e) => setS({ ...s, min_orders: e.target.value })} />
              </label>
              <label className="text-xs font-medium text-slate-500">WhatsApp template name (outside the 24-hour window)
                <Input className="mt-1" placeholder="usual_order" disabled={!manage} value={s.template}
                  onChange={(e) => setS({ ...s, template: e.target.value })} />
              </label>
            </div>
            <details className="mt-3 text-xs text-slate-500">
              <summary className="cursor-pointer">Template to submit in Meta (category: Utility)</summary>
              <p className="mt-2">English: {o.template_hint.en}</p>
              <p className="mt-1" dir="rtl">العربية: {o.template_hint.ar}</p>
            </details>
            {manage && (
              <div className="mt-4 flex flex-wrap gap-2">
                <Button disabled={busy} onClick={save}>Save</Button>
                <Button variant="outline" disabled={busy || !o.enabled} onClick={runNow}><Send size={16} /> Send due reminders now</Button>
              </div>
            )}
            <p className="mt-2 text-xs text-slate-500">Messages go out between 09:00 and 21:00, at most once per customer until they order again.</p>
          </Card>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-slate-500">DUE NOW AND IN THE NEXT 7 DAYS</h2>
            <Card className="overflow-hidden">
              <TableScroll>
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                    <tr><th className="px-4 py-3 font-medium">Customer</th><th className="px-4 py-3 font-medium">Usually orders every</th>
                      <th className="px-4 py-3 font-medium">Last order</th><th className="px-4 py-3 font-medium">Reminder</th></tr>
                  </thead>
                  <tbody>
                    {o.upcoming.map((u) => (
                      <tr key={u.customer_id} className="border-b border-[var(--border)] last:border-0">
                        <td className="px-4 py-3">{u.customer}</td>
                        <td className="px-4 py-3 tabular-nums">{u.typical_days} day{u.typical_days === 1 ? "" : "s"}</td>
                        <td className="px-4 py-3">{u.last_order_on}</td>
                        <td className={`px-4 py-3 ${u.days_late >= 0 ? "font-medium text-amber-700" : "text-slate-500"}`}>
                          {u.days_late >= 0 ? `Due (${u.days_late} day${u.days_late === 1 ? "" : "s"} late)` : `From ${u.due_on}`}
                        </td>
                      </tr>
                    ))}
                    {o.upcoming.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Nobody is due this week.</td></tr>}
                  </tbody>
                </table>
              </TableScroll>
            </Card>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-slate-500">SENT</h2>
            <Card className="overflow-hidden">
              <TableScroll>
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                    <tr><th className="px-4 py-3 font-medium">Customer</th><th className="px-4 py-3 font-medium">Offered</th>
                      <th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">Result</th></tr>
                  </thead>
                  <tbody>
                    {o.nudges.map((n) => (
                      <tr key={n.id} className="border-b border-[var(--border)] last:border-0 align-top">
                        <td className="px-4 py-3"><div>{n.customer}</div><div className="text-xs text-slate-400">{when(n.sent_at ?? n.created_at)}</div></td>
                        <td className="px-4 py-3 text-xs text-slate-600">{n.suggested.map((i) => `${i.quantity} × ${i.name}`).join(", ")}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS[n.status] ?? "bg-gray-100"}`}>{n.status}</span>
                          {n.error && <div className="mt-1 max-w-xs text-xs text-slate-500">{n.error}</div>}
                        </td>
                        <td className="px-4 py-3 text-xs">
                          {n.converted_order
                            ? <span className="text-emerald-700">Ordered {n.converted_order} ({n.currency} {Number(n.converted_amount).toLocaleString()})</span>
                            : <span className="text-slate-400">—</span>}
                        </td>
                      </tr>
                    ))}
                    {o.nudges.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No reminders sent yet.</td></tr>}
                  </tbody>
                </table>
              </TableScroll>
            </Card>
          </section>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
    </Card>
  );
}
