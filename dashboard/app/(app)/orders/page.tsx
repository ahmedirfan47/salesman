"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { OrderProgress } from "@/components/order-progress";
import { TableScroll } from "@/components/table-scroll";
import { useBranches } from "@/lib/branches";

type Order = {
  id: string;
  branch_id: string;
  order_number: string;
  status: string;
  customer_name: string | null;
  total_amount: string;
  currency: string;
  created_at: string;
};

export default function OrdersPage() {
  const router = useRouter();
  const { current, branches, nameOf } = useBranches();
  const showBranch = !current && branches.length > 1;
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/orders")
      .then(setOrders)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="mb-1 text-2xl font-bold">Orders</h1>
          <p className="text-sm text-slate-500">{orders.length} orders</p>
        </div>
        <Link href="/orders/new">
          <Button className="w-full sm:w-auto">
            <Plus size={16} />
            New Order
          </Button>
        </Link>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Order</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                {showBranch && <th className="px-4 py-3 font-medium">Branch</th>}
                <th className="px-4 py-3 font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Progress</th>
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
                  {showBranch && <td className="px-4 py-3 text-slate-600">{nameOf(o.branch_id)}</td>}
                  <td className="px-4 py-3">{o.currency} {Number(o.total_amount).toLocaleString()}</td>
                  <td className="px-4 py-3"><OrderProgress status={o.status} compact /></td>
                </tr>
              ))}
              {orders.length === 0 && !error && (
                <tr><td colSpan={showBranch ? 5 : 4} className="px-4 py-8 text-center text-slate-400">No orders yet</td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </div>
  );
}