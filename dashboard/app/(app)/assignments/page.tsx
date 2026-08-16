"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ShieldAlert, Truck } from "lucide-react";

type Order = { id: string; order_number: string; status: string; customer_name: string | null; total_amount: string; currency: string; zone_id: string | null; assigned_driver_id: string | null };
type Zone = { id: string; name: string };

export default function AssignmentsPage() {
  const { me, loading } = useMe();
  const [orders, setOrders] = useState<Order[]>([]);
  const [zones, setZones] = useState<Zone[]>([]);
  const [error, setError] = useState("");
  const [choice, setChoice] = useState<Record<string, { zone_id?: string; driver_id?: string; driver_name?: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    Promise.all([api("/orders"), api("/zones")])
      .then(([o, z]) => {
        setOrders(o.filter((x: Order) => x.status === "confirmed"));
        setZones(z);
      })
      .catch((e) => setError(e.message));
  }
  useEffect(() => { if (can(me, "dispatch_order")) load(); }, [me]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!can(me, "dispatch_order")) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Dispatchers only</h1>
        <p className="mt-2 text-sm text-slate-500">Your role ({me?.role}) can't access the assignment queue.</p>
      </Card>
    );
  }

  async function pickZone(orderId: string, zoneId: string) {
    setChoice((c) => ({ ...c, [orderId]: { zone_id: zoneId } }));
    if (!zoneId) return;
    try {
      const s = await api(`/zones/suggest-driver/${zoneId}`);
      setChoice((c) => ({ ...c, [orderId]: { zone_id: zoneId, driver_id: s.driver_id ?? undefined, driver_name: s.driver_name ?? undefined } }));
    } catch { /* ignore */ }
  }

  async function assign(orderId: string, alsoDispatch: boolean) {
    const c = choice[orderId];
    if (!c?.zone_id || !c?.driver_id) { setError("Pick a zone with a covering driver first."); return; }
    setBusy(orderId); setError("");
    try {
      await api(`/zones/assign/${orderId}`, { method: "POST", body: JSON.stringify({ zone_id: c.zone_id, driver_id: c.driver_id }) });
      if (alsoDispatch) {
        await api(`/orders/${orderId}/transition`, { method: "POST", body: JSON.stringify({ to_status: "dispatched" }) });
      }
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Assignment Queue</h1>
      <p className="mb-6 text-sm text-slate-500">Confirmed orders waiting to be assigned to a driver</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {orders.length === 0 ? (
        <Card className="p-8 text-center text-slate-400">Nothing waiting to assign.</Card>
      ) : (
        <div className="space-y-3">
          {orders.map((o) => {
            const c = choice[o.id] || {};
            return (
              <Card key={o.id} className="p-5">
                <div className="flex flex-wrap items-center gap-4">
                  <div className="min-w-[160px]">
                    <div className="font-mono text-xs text-slate-500">{o.order_number}</div>
                    <div className="font-medium">{o.customer_name ?? "—"}</div>
                    <div className="text-sm text-slate-500">{o.currency} {Number(o.total_amount).toLocaleString()}</div>
                  </div>

                  <div className="flex-1">
                    <label className="mb-1 block text-xs font-medium text-slate-500">Zone</label>
                    <select value={c.zone_id ?? ""} onChange={(e) => pickZone(o.id, e.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm">
                      <option value="">Select zone…</option>
                      {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
                    </select>
                  </div>

                  <div className="flex-1">
                    <label className="mb-1 block text-xs font-medium text-slate-500">Suggested driver</label>
                    <div className="rounded-lg border border-[var(--border)] bg-gray-50 px-3 py-2 text-sm">
                      {c.zone_id ? (c.driver_name ?? <span className="text-red-500">No driver covers this zone</span>) : <span className="text-slate-400">Pick a zone</span>}
                    </div>
                  </div>

                  <div className="flex shrink-0 gap-2 self-end">
                    <Button variant="outline" disabled={busy === o.id || !c.driver_id} onClick={() => assign(o.id, false)}>Assign</Button>
                    <Button disabled={busy === o.id || !c.driver_id} onClick={() => assign(o.id, true)}>
                      <Truck size={16} /> Assign & Dispatch
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}