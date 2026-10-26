"use client";

import { useEffect, useState } from "react";
import { api, downloadFile } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Download } from "lucide-react";
import { TableScroll } from "@/components/table-scroll";

type Summary = {
  date: string;
  currency: string;
  totals: {
    total_orders: number;
    confirmed_orders: number;
    cancelled_orders: number;
    review_orders: number;
    total_revenue: number;
    avg_order_value: number;
    total_units_sold: number;
  };
  products_sold: { sku: string; name: string; qty: number; revenue: number }[];
};

function today() {
  return new Date().toISOString().slice(0, 10);
}

export default function ReportsPage() {
  const [day, setDay] = useState(today());
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function load(d: string) {
    setError("");
    setLoading(true);
    try {
      const s = await api(`/reports/daily/summary?day=${d}`);
      setSummary(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(today());
  }, []);

  // goes through downloadFile so the PDF covers the branch selected in the sidebar
  async function downloadPdf() {
    try {
      await downloadFile(`/reports/daily/pdf?day=${day}`, `report-${day}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not download PDF");
    }
  }

  const t = summary?.totals;
  const cards = [
    { label: "Orders", value: t?.total_orders },
    { label: "Confirmed", value: t?.confirmed_orders },
    { label: `Revenue (${summary?.currency ?? ""})`, value: t ? t.total_revenue.toLocaleString() : undefined },
    { label: "Units sold", value: t?.total_units_sold },
  ];

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Daily Reports</h1>
      <p className="mb-6 text-sm text-slate-500">Pick a date to see that day's sales</p>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div>
          <label className="mb-1 block text-sm font-medium">Date</label>
          <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="w-full sm:w-48" />
        </div>
        <div className="flex gap-3">
          <Button variant="outline" onClick={() => load(day)} disabled={loading} className="flex-1 sm:flex-none">
            {loading ? "Loading…" : "Load"}
          </Button>
          <Button onClick={downloadPdf} disabled={!summary} className="flex-1 sm:flex-none">
            <Download size={16} />
            Download PDF
          </Button>
        </div>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {summary && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {cards.map((c) => (
              <Card key={c.label} className="p-5">
                <div className="text-sm font-medium text-slate-500">{c.label}</div>
                <div className="mt-2 text-2xl font-bold">{c.value ?? "—"}</div>
              </Card>
            ))}
          </div>

          <h2 className="mb-3 text-sm font-semibold text-slate-500">PRODUCTS SOLD</h2>
          <Card className="overflow-hidden">
            <TableScroll>
              <table className="w-full min-w-[560px] text-sm">
                <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                  <tr>
                    <th className="px-4 py-3 font-medium">SKU</th>
                    <th className="px-4 py-3 font-medium">Product</th>
                    <th className="px-4 py-3 font-medium text-right">Qty</th>
                    <th className="px-4 py-3 font-medium text-right">Revenue</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.products_sold.map((p) => (
                    <tr key={p.sku} className="border-b border-[var(--border)] last:border-0">
                      <td className="px-4 py-3 font-mono text-xs">{p.sku}</td>
                      <td className="px-4 py-3">{p.name}</td>
                      <td className="px-4 py-3 text-right">{p.qty}</td>
                      <td className="px-4 py-3 text-right">{p.revenue.toLocaleString()}</td>
                    </tr>
                  ))}
                  {summary.products_sold.length === 0 && (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No sales on this day</td></tr>
                  )}
                </tbody>
              </table>
            </TableScroll>
          </Card>
        </>
      )}
    </div>
  );
}