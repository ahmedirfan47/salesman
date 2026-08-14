"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Package, ShoppingCart, DollarSign, AlertTriangle } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
} from "recharts";

type Order = { status: string; total_amount: string; order_number: string };

const STATUS_COLORS: Record<string, string> = {
  confirmed: "#10b981",
  completed: "#059669",
  requires_human_review: "#f59e0b",
  cancelled: "#ef4444",
  pending: "#94a3b8",
};

export default function OverviewPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [productCount, setProductCount] = useState(0);
  const [escalationCount, setEscalationCount] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [products, ord, esc] = await Promise.all([
          api("/products"),
          api("/orders"),
          api("/orders/escalations/open"),
        ]);
        setProductCount(products.length);
        setOrders(ord);
        setEscalationCount(esc.length);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    }
    load();
  }, []);

  const revenue = orders
    .filter((o) => o.status === "confirmed" || o.status === "completed")
    .reduce((s, o) => s + Number(o.total_amount), 0);

  const byStatus = Object.entries(
    orders.reduce<Record<string, number>>((acc, o) => {
      acc[o.status] = (acc[o.status] || 0) + 1;
      return acc;
    }, {})
  ).map(([status, count]) => ({ status, count }));

  const revenueBars = orders
    .filter((o) => o.status === "confirmed" || o.status === "completed")
    .slice(0, 8)
    .reverse()
    .map((o) => ({ name: o.order_number, revenue: Number(o.total_amount) }));

  const cards = [
    { label: "Products", value: productCount, icon: Package, color: "text-indigo-600" },
    { label: "Orders", value: orders.length, icon: ShoppingCart, color: "text-emerald-600" },
    { label: "Revenue", value: `$${revenue.toLocaleString()}`, icon: DollarSign, color: "text-amber-600" },
    { label: "Open escalations", value: escalationCount, icon: AlertTriangle, color: "text-red-600" },
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <h3 className="mb-4 text-sm font-semibold text-slate-500">REVENUE BY ORDER</h3>
          {revenueBars.length === 0 ? (
            <p className="py-12 text-center text-sm text-slate-400">No confirmed orders yet</p>
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
                  {byStatus.map((entry) => (
                    <Cell key={entry.status} fill={STATUS_COLORS[entry.status] ?? "#94a3b8"} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>
    </div>
  );
}