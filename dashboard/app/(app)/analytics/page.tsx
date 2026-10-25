"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { ShieldAlert, Info, AlertTriangle, Save } from "lucide-react";

type Summary = {
  days: number;
  currency: string | null;
  revenue: number;
  order_count: number;
  costed_revenue: number;
  costed_cost: number;
  costed_profit: number;
  margin_percent: number | null;
  cost_coverage_percent: number;
  products_missing_cost: number;
};
type Margin = { sku: string; name: string; units_sold: number; revenue: number; cost: number; profit: number; margin_percent: number | null };
type ProductCost = {
  product_id: string; sku: string; name: string; is_active: boolean;
  cost_price: number | null; cost_currency: string | null;
  sell_price: number | null; sell_currency: string | null; current_margin_percent: number | null;
};
type Drifting = { customer_id: string; name: string; last_order_at: string | null; days_since_last_order: number; typical_gap_days: number | null; order_count: number };
type Stuck = { order_id: string; order_number: string; status: string; customer_name: string | null; hours_in_status: number; threshold_hours: number };

type Tab = "margins" | "costs" | "customers" | "stuck";
const PERIODS = [7, 30, 90];

const money = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });

function MarginBadge({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-slate-500">Unknown</span>;
  }
  const tone = value < 0 ? "bg-red-50 text-red-700" : value < 10 ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>{value.toFixed(1)}%</span>;
}

function marginOf(sell: number | null, cost: number | null): number | null {
  if (sell == null || cost == null || sell <= 0) return null;
  return Math.round(((sell - cost) / sell) * 1000) / 10;
}

export default function AnalyticsPage() {
  const { me } = useMe();
  const allowed = can(me, "view_analytics");
  const canEditCosts = can(me, "manage_products");

  const [days, setDays] = useState(30);
  const [tab, setTab] = useState<Tab>("margins");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [margins, setMargins] = useState<Margin[]>([]);
  const [costs, setCosts] = useState<ProductCost[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [drifting, setDrifting] = useState<Drifting[]>([]);
  const [stuck, setStuck] = useState<Stuck[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  async function load(d: number) {
    setLoading(true);
    setError("");
    try {
      const [s, m, c, dr, st] = await Promise.all([
        api(`/analytics/summary?days=${d}`),
        api(`/analytics/margins?days=${d}`),
        api("/analytics/product-costs"),
        api("/analytics/drifting-customers"),
        api("/analytics/stuck-orders"),
      ]);
      setSummary(s);
      setMargins(m);
      setCosts(c);
      setDrafts({});
      setDrifting(dr);
      setStuck(st);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (allowed) load(days);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed, days]);

  const changed = useMemo(
    () =>
      costs.filter((c) => {
        if (!(c.product_id in drafts)) return false;
        const raw = drafts[c.product_id].trim();
        const next = raw === "" ? null : Number(raw);
        return next !== c.cost_price;
      }),
    [costs, drafts],
  );
  const invalid = changed.some((c) => {
    const raw = drafts[c.product_id].trim();
    return raw !== "" && (!Number.isFinite(Number(raw)) || Number(raw) < 0);
  });

  async function saveCosts() {
    if (!changed.length || invalid) return;
    setSaving(true);
    setError("");
    setMsg("");
    try {
      const items = changed.map((c) => {
        const raw = drafts[c.product_id].trim();
        return { product_id: c.product_id, cost_price: raw === "" ? null : raw };
      });
      const res = await api("/analytics/product-costs", { method: "PUT", body: JSON.stringify({ items }) });
      setMsg(`Saved ${res.updated} cost price${res.updated === 1 ? "" : "s"}. They apply to orders from now on.`);
      await load(days);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save costs");
    } finally {
      setSaving(false);
    }
  }

  if (!me) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  if (!allowed) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Owners and admins only</h1>
        <p className="mt-2 text-sm text-slate-500">Margins and cost prices are visible to owners and admins.</p>
      </Card>
    );
  }

  const ccy = summary?.currency ?? "";
  const cards = [
    { label: `Revenue (${ccy})`, value: money(summary?.revenue), sub: `${summary?.order_count ?? 0} orders` },
    { label: `Gross profit (${ccy})`, value: summary?.margin_percent == null ? "—" : money(summary?.costed_profit), sub: "on lines with a known cost" },
    { label: "Gross margin", value: summary?.margin_percent == null ? "—" : `${summary.margin_percent.toFixed(1)}%`, sub: "on lines with a known cost" },
    { label: "Cost coverage", value: summary ? `${summary.cost_coverage_percent.toFixed(0)}%` : "—", sub: "of revenue has cost data" },
  ];

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "margins", label: "Margins by product" },
    { id: "costs", label: "Cost prices", count: summary?.products_missing_cost || undefined },
    { id: "customers", label: "Customers going quiet", count: drifting.length || undefined },
    { id: "stuck", label: "Stuck orders", count: stuck.length || undefined },
  ];

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="mb-1 text-2xl font-bold">Analytics</h1>
          <p className="text-sm text-slate-500">Margins, cost prices and the customers and orders that need attention</p>
        </div>
        <div className="flex rounded-lg border border-[var(--border)] bg-white p-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setDays(p)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                days === p ? "bg-[var(--primary)] text-white" : "text-slate-600 hover:bg-gray-100"
              }`}
            >
              {p} days
            </button>
          ))}
        </div>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.label} className="p-5">
            <div className="text-sm font-medium text-slate-500">{c.label}</div>
            <div className="mt-2 text-2xl font-bold">{loading && !summary ? "…" : c.value}</div>
            <div className="mt-1 text-xs text-slate-400">{c.sub}</div>
          </Card>
        ))}
      </div>

      {summary && summary.products_missing_cost > 0 && (
        <Card className="mb-6 flex flex-col gap-3 border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3 text-sm text-amber-900">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <span>
              {summary.products_missing_cost} active product{summary.products_missing_cost === 1 ? " has" : "s have"} no cost
              price, so their margins show as unknown. Add costs to start tracking profit on new orders.
            </span>
          </div>
          <Button variant="outline" onClick={() => setTab("costs")} className="shrink-0">Enter cost prices</Button>
        </Card>
      )}

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-[var(--border)]">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition ${
              tab === t.id ? "border-[var(--primary)] text-[var(--primary)]" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
            {t.count != null && (
              <span className="rounded-full bg-gray-100 px-1.5 text-xs font-semibold text-slate-600">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "margins" && (
        <Card className="overflow-hidden">
          <TableScroll>
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">SKU</th>
                  <th className="px-4 py-3 font-medium">Product</th>
                  <th className="px-4 py-3 text-right font-medium">Units</th>
                  <th className="px-4 py-3 text-right font-medium">Revenue</th>
                  <th className="px-4 py-3 text-right font-medium">Cost</th>
                  <th className="px-4 py-3 text-right font-medium">Profit</th>
                  <th className="px-4 py-3 text-right font-medium">Margin</th>
                </tr>
              </thead>
              <tbody>
                {margins.map((m) => (
                  <tr key={m.sku} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3 font-mono text-xs">{m.sku}</td>
                    <td className="px-4 py-3">{m.name}</td>
                    <td className="px-4 py-3 text-right">{m.units_sold.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right">{money(m.revenue)}</td>
                    <td className="px-4 py-3 text-right">{m.margin_percent == null ? "—" : money(m.cost)}</td>
                    <td className="px-4 py-3 text-right">{m.margin_percent == null ? "—" : money(m.profit)}</td>
                    <td className="px-4 py-3 text-right"><MarginBadge value={m.margin_percent} /></td>
                  </tr>
                ))}
                {margins.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-400">No sales in the last {days} days</td></tr>
                )}
              </tbody>
            </table>
          </TableScroll>
          <p className="flex items-start gap-2 border-t border-[var(--border)] px-4 py-3 text-xs text-slate-500">
            <Info size={14} className="mt-0.5 shrink-0" />
            Margins use the cost recorded when each order was placed. Orders placed before a product had a cost show as unknown, so a margin is never guessed.
          </p>
        </Card>
      )}

      {tab === "costs" && (
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-[var(--border)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-500">
              What each product costs you to buy. Applies to orders from now on; past orders keep their original cost.
            </p>
            {canEditCosts && (
              <Button onClick={saveCosts} disabled={!changed.length || invalid || saving} className="shrink-0">
                <Save size={16} />
                {saving ? "Saving…" : changed.length ? `Save ${changed.length} change${changed.length === 1 ? "" : "s"}` : "Save"}
              </Button>
            )}
          </div>
          <TableScroll>
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">SKU</th>
                  <th className="px-4 py-3 font-medium">Product</th>
                  <th className="px-4 py-3 text-right font-medium">Sell price</th>
                  <th className="px-4 py-3 text-right font-medium">Cost price</th>
                  <th className="px-4 py-3 text-right font-medium">Margin at today&apos;s price</th>
                </tr>
              </thead>
              <tbody>
                {costs.map((c) => {
                  const draft = drafts[c.product_id];
                  const shown = draft ?? (c.cost_price == null ? "" : String(c.cost_price));
                  const n = shown.trim() === "" ? null : Number(shown);
                  const bad = n != null && (!Number.isFinite(n) || n < 0);
                  const live = bad ? null : marginOf(c.sell_price, n);
                  return (
                    <tr key={c.product_id} className={`border-b border-[var(--border)] last:border-0 ${c.is_active ? "" : "opacity-50"}`}>
                      <td className="px-4 py-2 font-mono text-xs">{c.sku}</td>
                      <td className="px-4 py-2">{c.name}{!c.is_active && <span className="ml-2 text-xs text-slate-400">inactive</span>}</td>
                      <td className="px-4 py-2 text-right">
                        {c.sell_price == null ? <span className="text-slate-400">No price</span> : `${money(c.sell_price)} ${c.sell_currency ?? ""}`}
                      </td>
                      <td className="px-4 py-2 text-right">
                        {canEditCosts ? (
                          <div className="ml-auto w-32">
                            <Input
                              inputMode="decimal"
                              value={shown}
                              placeholder="Not set"
                              onChange={(e) => setDrafts((d) => ({ ...d, [c.product_id]: e.target.value }))}
                              className={`text-right ${bad ? "border-red-400" : ""}`}
                              aria-label={`Cost price for ${c.name}`}
                            />
                          </div>
                        ) : (
                          money(c.cost_price)
                        )}
                      </td>
                      <td className="px-4 py-2 text-right"><MarginBadge value={live} /></td>
                    </tr>
                  );
                })}
                {costs.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No products yet. Upload a price sheet on the Pricing page.</td></tr>
                )}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}

      {tab === "customers" && (
        <Card className="overflow-hidden">
          <p className="border-b border-[var(--border)] px-4 py-3 text-sm text-slate-500">
            Customers whose silence is more than twice their usual gap between orders. Each customer is compared with their own rhythm, not a fixed number of days.
          </p>
          <TableScroll>
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 text-right font-medium">Orders</th>
                  <th className="px-4 py-3 text-right font-medium">Usually orders every</th>
                  <th className="px-4 py-3 text-right font-medium">Days since last order</th>
                  <th className="px-4 py-3 text-right font-medium">Last order</th>
                </tr>
              </thead>
              <tbody>
                {drifting.map((d) => (
                  <tr key={d.customer_id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3 font-medium">{d.name}</td>
                    <td className="px-4 py-3 text-right">{d.order_count}</td>
                    <td className="px-4 py-3 text-right">{d.typical_gap_days == null ? "—" : `${d.typical_gap_days} days`}</td>
                    <td className="px-4 py-3 text-right font-semibold text-amber-700">{d.days_since_last_order}</td>
                    <td className="px-4 py-3 text-right text-slate-500">{d.last_order_at ? new Date(d.last_order_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
                {drifting.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No customers have gone quiet. Customers need at least 3 orders to have a pattern.</td></tr>
                )}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}

      {tab === "stuck" && (
        <Card className="overflow-hidden">
          <p className="border-b border-[var(--border)] px-4 py-3 text-sm text-slate-500">
            Orders sitting in one status longer than expected: confirmed 4 h, preparing 8 h, dispatched 24 h, delivered 48 h.
          </p>
          <TableScroll>
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Order</th>
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 text-right font-medium">Time in status</th>
                  <th className="px-4 py-3 text-right font-medium">Expected within</th>
                </tr>
              </thead>
              <tbody>
                {stuck.map((o) => (
                  <tr key={o.order_id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3">
                      <Link href={`/orders/${o.order_id}`} className="font-mono text-xs font-semibold text-[var(--primary)] hover:underline">{o.order_number}</Link>
                    </td>
                    <td className="px-4 py-3">{o.customer_name ?? "—"}</td>
                    <td className="px-4 py-3 capitalize">{o.status}</td>
                    <td className="px-4 py-3 text-right font-semibold text-red-700">
                      {o.hours_in_status >= 48 ? `${Math.round(o.hours_in_status / 24)} days` : `${Math.round(o.hours_in_status)} h`}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-500">{o.threshold_hours} h</td>
                  </tr>
                ))}
                {stuck.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">Nothing is stuck. Every open order is moving on time.</td></tr>
                )}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}
    </div>
  );
}