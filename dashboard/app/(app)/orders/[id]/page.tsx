"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Truck, PackageCheck, CheckCircle2, XCircle } from "lucide-react";

type Item = { id: string; sku: string; product_name: string; quantity: number; unit_price: string; line_total: string };
type Event = { from_status: string | null; to_status: string; actor_name: string | null; note: string | null; created_at: string };
type Order = {
  id: string; order_number: string; status: string;
  customer_name: string | null; total_amount: string; currency: string;
  created_at: string; items: Item[]; events: Event[];
};

const statusColor: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-700",
  dispatched: "bg-blue-50 text-blue-700",
  delivered: "bg-indigo-50 text-indigo-700",
  completed: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-red-50 text-red-700",
  requires_human_review: "bg-amber-50 text-amber-700",
};

const nextActions: Record<string, { to: string; label: string; icon: typeof Truck; variant?: "primary" | "danger" }[]> = {
  confirmed: [
    { to: "dispatched", label: "Mark Dispatched", icon: Truck },
    { to: "cancelled", label: "Cancel", icon: XCircle, variant: "danger" },
  ],
  dispatched: [
    { to: "delivered", label: "Mark Delivered", icon: PackageCheck },
    { to: "cancelled", label: "Cancel", icon: XCircle, variant: "danger" },
  ],
  delivered: [
    { to: "completed", label: "Complete Order", icon: CheckCircle2 },
  ],
};

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api(`/orders/${id}`)
      .then(setOrder)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [id]);

  async function transition(to: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/orders/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_status: to }),
      });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (!order) {
    return (
      <div>
        <Link href="/orders" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft size={16} /> Back</Link>
        {error ? <p className="text-red-600">{error}</p> : <p className="text-slate-400">Loading…</p>}
      </div>
    );
  }

  const actions = nextActions[order.status] ?? [];

  return (
    <div className="max-w-3xl">
      <Link href="/orders" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft size={16} /> Back to Orders
      </Link>

      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{order.order_number}</h1>
          <p className="text-sm text-slate-500">{order.customer_name ?? "—"}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-sm font-medium ${statusColor[order.status] ?? "bg-gray-100"}`}>
          {order.status.replace(/_/g, " ")}
        </span>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {actions.length > 0 && (
        <div className="mb-6 flex gap-3">
          {actions.map((a) => (
            <Button key={a.to} variant={a.variant ?? "primary"} disabled={busy} onClick={() => transition(a.to)}>
              <a.icon size={16} />
              {a.label}
            </Button>
          ))}
        </div>
      )}

      <Card className="mb-6 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Product</th>
              <th className="px-4 py-3 font-medium text-right">Qty</th>
              <th className="px-4 py-3 font-medium text-right">Unit</th>
              <th className="px-4 py-3 font-medium text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((it) => (
              <tr key={it.id} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-3">{it.product_name} <span className="text-xs text-slate-400">({it.sku})</span></td>
                <td className="px-4 py-3 text-right">{it.quantity}</td>
                <td className="px-4 py-3 text-right">{Number(it.unit_price).toLocaleString()}</td>
                <td className="px-4 py-3 text-right">{Number(it.line_total).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="font-semibold">
              <td className="px-4 py-3" colSpan={3}>Total</td>
              <td className="px-4 py-3 text-right">{order.currency} {Number(order.total_amount).toLocaleString()}</td>
            </tr>
          </tfoot>
        </table>
      </Card>

      <h2 className="mb-3 text-sm font-semibold text-slate-500">TIMELINE</h2>
      <Card className="p-5">
        <ol className="space-y-4">
          <li className="flex gap-3">
            <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-slate-300" />
            <div>
              <div className="text-sm font-medium">Order created</div>
              <div className="text-xs text-slate-400">{new Date(order.created_at).toLocaleString()}</div>
            </div>
          </li>
          {order.events.map((e, i) => (
            <li key={i} className="flex gap-3">
              <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[var(--primary)]" />
              <div>
                <div className="text-sm font-medium">
                  {e.to_status.replace(/_/g, " ")}
                  {e.actor_name && <span className="font-normal text-slate-500"> — by {e.actor_name}</span>}
                </div>
                <div className="text-xs text-slate-400">{new Date(e.created_at).toLocaleString()}</div>
              </div>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}