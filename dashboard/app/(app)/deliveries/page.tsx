"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PackageCheck, ShieldAlert, MapPin } from "lucide-react";

type Order = { id: string; order_number: string; status: string; customer_name: string | null; total_amount: string; currency: string };

export default function DeliveriesPage() {
  const { me, loading } = useMe();
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    api("/zones/my-deliveries/list").then(setOrders).catch((e) => setError(e.message));
  }
  useEffect(() => { if (can(me, "deliver_order")) load(); }, [me]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!can(me, "deliver_order")) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Drivers only</h1>
        <p className="mt-2 text-sm text-slate-500">This screen is for delivery drivers.</p>
      </Card>
    );
  }

  async function markDelivered(id: string) {
    setBusy(id); setError("");
    try {
      await api(`/orders/${id}/transition`, { method: "POST", body: JSON.stringify({ to_status: "delivered" }) });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  const active = orders.filter((o) => o.status === "dispatched");
  const done = orders.filter((o) => o.status === "delivered");

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 text-2xl font-bold">My Deliveries</h1>
      <p className="mb-6 text-sm text-slate-500">Orders assigned to you</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <h2 className="mb-3 text-sm font-semibold text-slate-500">TO DELIVER ({active.length})</h2>
      {active.length === 0 ? (
        <Card className="mb-6 p-6 text-center text-slate-400">No active deliveries right now.</Card>
      ) : (
        <div className="mb-6 space-y-3">
          {active.map((o) => (
            <Card key={o.id} className="p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="flex items-center gap-2 font-medium"><MapPin size={16} className="text-[var(--primary)]" /> {o.customer_name ?? "—"}</div>
                  <div className="font-mono text-xs text-slate-500">{o.order_number} · {o.currency} {Number(o.total_amount).toLocaleString()}</div>
                </div>
                <Button disabled={busy === o.id} onClick={() => markDelivered(o.id)} className="w-full sm:w-auto">
                  <PackageCheck size={16} /> Mark Delivered
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {done.length > 0 && (
        <>
          <h2 className="mb-3 text-sm font-semibold text-slate-500">DELIVERED ({done.length})</h2>
          <div className="space-y-2">
            {done.map((o) => (
              <Card key={o.id} className="flex items-center justify-between p-4 text-sm">
                <span>{o.customer_name ?? "—"} <span className="font-mono text-xs text-slate-400">{o.order_number}</span></span>
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">delivered</span>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}