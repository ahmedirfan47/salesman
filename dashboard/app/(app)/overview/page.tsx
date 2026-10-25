"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Package, ShoppingCart, Banknote, AlertTriangle } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, CartesianGrid,
} from "recharts";

type Order = { id: string; order_number: string; status: string; total_amount: string; currency: string; customer_name: string | null };
type CatalogRow = { sku: string; name_en: string; stock: number };

const STATUS_COLORS: Record<string, string> = {
  confirmed: "#10b981", completed: "#059669", dispatched: "#3b82f6",
  delivered: "#6366f1", requires_human_review: "#f59e0b", cancelled: "#ef4444", pending: "#94a3b8",
};
const LOW_STOCK = 10;

export default function OverviewPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [escalations, setEscalations] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [ord, cat, esc] = await Promise.all([
          api("/orders"),
          api("/products/catalog"),
          api("/orders/escalations/open"),
        ]);
        setOrders(ord);
        setCatalog(cat);
        setEscalations(esc.length);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    }
    load();
  }, []);

  const revenue = orders
    .filter((o) => ["confirmed", "dispatched", "delivered", "completed"].includes(o.status))
    .reduce((s, o) => s + Number(o.total_amount), 0);

  const byStatus = Object.entries(
    orders.reduce<Record<string, number>>((acc, o) => { acc[o.status] = (acc[o.status] || 0) + 1; return acc; }, {})
  ).map(([status, count]) => ({ status, count }));

  const revenueBars = orders
    .filter((o) => ["confirmed", "dispatched", "delivered", "completed"].includes(o.status))
    .slice(0, 8).reverse()
    .map((o) => ({ name: o.order_number, revenue: Number(o.total_amount) }));

  const lowStock = catalog.filter((c) => c.stock <= LOW_STOCK).sort((a, b) => a.stock - b.stock);
  const recentOrders = orders.slice(0, 6);

  const cards = [
    { label: "Products", value: catalog.length, icon: Package, color: "text-indigo-600" },
    { label: "Orders", value: orders.length, icon: ShoppingCart, color: "text-emerald-600" },
    { label: "Revenue", value: `${orders[0]?.currency ?? ""} ${revenue.toLocaleString()}`.trim(), icon: Banknote, color: "text-amber-600" },
    { label: "Open escalations", value: escalations, icon: AlertTriangle, color: "text-red-600" },
  ];

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Overview</h1>
      <p className="mb-6 text-sm text-slate-500">Your business at a glance</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(({ label, value, icon: Icon, color }) => (
          <Card key={label} className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">{label}</span>
              <Icon size={20} className={color} />
            </div>
            <div className="mt-3 text-3xl font-bold">{value}</div>
          </Card>
        ))}
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <h3 className="mb-4 text-sm font-semibold text-slate-500">REVENUE BY ORDER</h3>
          {revenueBars.length === 0 ? (
            <p className="py-12 text-center text-sm text-slate-400">No orders yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={revenueBars}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="revenue" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
        <Card className="p-5">
          <h3 className="mb-4 text-sm font-semibold text-slate-500">ORDERS BY STATUS</h3>
          {byStatus.length === 0 ? (
            <p className="py-12 text-center text-sm text-slate-400">No orders yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={byStatus} dataKey="count" nameKey="status" cx="50%" cy="50%" outerRadius={80} label>
                  {byStatus.map((e) => <Cell key={e.status} fill={STATUS_COLORS[e.status] ?? "#94a3b8"} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-500">
            <AlertTriangle size={16} className="text-red-500" /> LOW STOCK
          </h3>
          {lowStock.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">Everything well stocked</p>
          ) : (
            <div className="space-y-2">
              {lowStock.slice(0, 6).map((c) => (
                <div key={c.sku} className="flex items-center justify-between text-sm">
                  <span>{c.name_en} <span className="text-xs text-slate-400">({c.sku})</span></span>
                  <span className="font-semibold text-red-600">{c.stock} left</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-5">
          <h3 className="mb-4 text-sm font-semibold text-slate-500">RECENT ORDERS</h3>
          {recentOrders.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">No orders yet</p>
          ) : (
            <div className="space-y-2">
              {recentOrders.map((o) => (
                <Link key={o.id} href={`/orders/${o.id}`} className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-gray-50">
                  <span className="font-mono text-xs">{o.order_number}</span>
                  <span className="text-slate-600">{o.customer_name ?? "—"}</span>
                  <span className="font-medium">{o.currency} {Number(o.total_amount).toLocaleString()}</span>
                </Link>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}