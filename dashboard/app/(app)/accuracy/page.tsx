"use client";

import { useEffect, useState } from "react";
import { api, getToken, isDemo } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { Download, Target } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Row = {
  key: string; customer: string; orders: number; confirmed: number; approved: number; corrected: number; rejected: number;
  waiting: number; decided: number; lines: number; lines_changed: number; order_accuracy: number | null;
  line_accuracy: number | null; minutes_saved: number;
};
type Report = { month: string; period: { from: string; to: string }; totals: Row; customers: Row[]; minutes_per_order: number };

const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
const tone = (v: number | null) => (v === null ? "text-slate-400" : v >= 90 ? "text-emerald-700" : v >= 75 ? "text-amber-700" : "text-red-600");

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function AccuracyPage() {
  const [month, setMonth] = useState(thisMonth());
  const [r, setR] = useState<Report | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setR(null);
    setError("");
    api(`/reports/accuracy?month=${month}`).then(setR).catch((e) => setError(e.message));
  }, [month]);

  function download() {
    if (isDemo()) {
      setError("Downloads aren't available in the demo.");
      return;
    }
    fetch(`${API_BASE}/api/v1/reports/accuracy.csv?month=${month}`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((res) => res.blob())
      .then((b) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(b);
        a.download = `ai-accuracy-${month}.csv`;
        a.click();
      });
  }

  const t = r?.totals;
  const hours = t ? Math.round((t.minutes_saved / 60) * 10) / 10 : 0;

  return (
    <div className="max-w-5xl">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Target size={22} /> AI accuracy</h1>
          <p className="text-sm text-slate-500">
            How often the AI&apos;s WhatsApp orders went through without your team changing them, per customer, each month.
          </p>
        </div>
        <div className="flex gap-2">
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value || thisMonth())} className="w-40" />
          <Button variant="outline" onClick={download}><Download size={16} /> CSV</Button>
        </div>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {!r && !error && <p className="text-slate-400">Loading…</p>}

      {r && t && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="AI orders" value={String(t.orders)} />
            <Kpi label="Order accuracy" value={pct(t.order_accuracy)} className={tone(t.order_accuracy)} />
            <Kpi label="Line accuracy" value={pct(t.line_accuracy)} className={tone(t.line_accuracy)} />
            <Kpi label="Typing saved (estimate)" value={`${hours} h`} />
          </div>

          <Card className="overflow-hidden">
            <TableScroll>
              <table className="w-full min-w-[820px] text-sm">
                <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">Customer</th>
                    <th className="px-3 py-3 text-right font-medium">AI orders</th>
                    <th className="px-3 py-3 text-right font-medium">Straight through</th>
                    <th className="px-3 py-3 text-right font-medium">Approved as is</th>
                    <th className="px-3 py-3 text-right font-medium">Corrected</th>
                    <th className="px-3 py-3 text-right font-medium">Rejected</th>
                    <th className="px-3 py-3 text-right font-medium">Waiting</th>
                    <th className="px-3 py-3 text-right font-medium">Order accuracy</th>
                    <th className="px-4 py-3 text-right font-medium">Line accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {r.customers.map((c) => <Line key={c.key} row={c} />)}
                  {r.customers.length === 0 && (
                    <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">No AI orders in {r.month}.</td></tr>
                  )}
                  {r.customers.length > 0 && <Line row={t} total />}
                </tbody>
              </table>
            </TableScroll>
          </Card>
          <p className="mt-3 text-xs text-slate-500">
            Order accuracy = orders that went straight through or were approved as they were, out of decided orders. Line
            accuracy counts the products and quantities your team changed (a rejected order counts all its lines). Orders held
            only for stock or credit count as straight through. Typing saved assumes {r.minutes_per_order} minutes per order.
          </p>
        </>
      )}
    </div>
  );
}

function Kpi({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${className}`}>{value}</div>
    </Card>
  );
}

function Line({ row, total }: { row: Row; total?: boolean }) {
  return (
    <tr className={`border-b border-[var(--border)] last:border-0 ${total ? "bg-gray-50 font-semibold" : ""}`}>
      <td className="px-4 py-3">{row.customer}</td>
      <td className="px-3 py-3 text-right tabular-nums">{row.orders}</td>
      <td className="px-3 py-3 text-right tabular-nums">{row.confirmed}</td>
      <td className="px-3 py-3 text-right tabular-nums">{row.approved}</td>
      <td className="px-3 py-3 text-right tabular-nums">{row.corrected}</td>
      <td className="px-3 py-3 text-right tabular-nums">{row.rejected}</td>
      <td className="px-3 py-3 text-right tabular-nums text-slate-400">{row.waiting}</td>
      <td className={`px-3 py-3 text-right tabular-nums ${tone(row.order_accuracy)}`}>{pct(row.order_accuracy)}</td>
      <td className={`px-4 py-3 text-right tabular-nums ${tone(row.line_accuracy)}`}>{pct(row.line_accuracy)}</td>
    </tr>
  );
}
