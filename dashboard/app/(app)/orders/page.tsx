"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

type Order = {
  id: string;
  order_number: string;
  status: string;
  customer_name: string | null;
  total_amount: string;
  currency: string;
  created_at: string;
};

const statusColor: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-700",
  dispatched: "bg-blue-50 text-blue-700",
  delivered: "bg-indigo-50 text-indigo-700",
  completed: "bg-emerald-100 text-emerald-800",
  requires_human_review: "bg-amber-50 text-amber-700",
  cancelled: "bg-red-50 text-red-700",
  pending: "bg-gray-100 text-gray-600",
};

export default function OrdersPage() {
  const router = useRouter();
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/orders")
      .then(setOrders)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="mb-1 text-2xl font-bold">Orders</h1>
          <p className="text-sm text-slate-500">{orders.length} orders</p>
        </div>
        <Link href="/orders/new">
          <Button>
            <Plus size={16} />
            New Order
          </Button>
        </Link>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Order</th>
              <th className="px-4 py-3 font-medium">Customer</th>
              <th className="px-4 py-3 font-medium">Total</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr
                key={o.id}
                onClick={() => router.push(`/orders/${o.id}`)}
                className="cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-gray-50"
              >
                <td className="px-4 py-3 font-mono text-xs">{o.order_number}</td>
                <td className="px-4 py-3">{o.customer_name ?? "—"}</td>
                <td className="px-4 py-3">{o.currency} {Number(o.total_amount).toLocaleString()}</td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${statusColor[o.status] ?? "bg-gray-100 text-gray-600"}`}>
                    {o.status.replace(/_/g, " ")}
                  </span>
                </td>
              </tr>
            ))}
            {orders.length === 0 && !error && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No orders yet</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}