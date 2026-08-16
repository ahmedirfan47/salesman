"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ShieldAlert, MapPin, Trash2 } from "lucide-react";

type Zone = { id: string; name: string; description: string | null };
type User = { id: string; full_name: string | null; email: string; role: string };

export default function ZonesPage() {
  const { me, loading } = useMe();
  const [zones, setZones] = useState<Zone[]>([]);
  const [drivers, setDrivers] = useState<User[]>([]);
  const [driverZones, setDriverZones] = useState<Record<string, string[]>>({});
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [z, users] = await Promise.all([api("/zones"), api("/users")]);
      setZones(z);
      const drv = users.filter((u: User) => u.role === "driver");
      setDrivers(drv);
      const map: Record<string, string[]> = {};
      for (const d of drv) {
        map[d.id] = await api(`/zones/drivers/${d.id}/zones`);
      }
      setDriverZones(map);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }
  useEffect(() => { if (can(me, "manage_users")) load(); }, [me]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!can(me, "manage_users")) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Admins only</h1>
      </Card>
    );
  }

  async function addZone() {
    if (!name.trim()) return;
    setBusy(true); setError("");
    try {
      await api("/zones", { method: "POST", body: JSON.stringify({ name }) });
      setName("");
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }
  async function removeZone(id: string) {
    try { await api(`/zones/${id}`, { method: "DELETE" }); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }
  async function toggleDriverZone(driverId: string, zoneId: string) {
    const current = driverZones[driverId] || [];
    const next = current.includes(zoneId) ? current.filter((z) => z !== zoneId) : [...current, zoneId];
    setDriverZones((m) => ({ ...m, [driverId]: next }));
    try { await api(`/zones/drivers/${driverId}/zones`, { method: "PUT", body: JSON.stringify({ zone_ids: next }) }); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); load(); }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Zones</h1>
      <p className="mb-6 text-sm text-slate-500">Delivery areas and which drivers cover them</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <Card className="mb-6 p-6">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-500"><MapPin size={16} /> ADD ZONE</h2>
        <div className="flex gap-2">
          <Input placeholder="e.g. Riyadh North" value={name} onChange={(e) => setName(e.target.value)} />
          <Button onClick={addZone} disabled={busy || !name.trim()}>Add</Button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {zones.map((z) => (
            <span key={z.id} className="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1 text-sm text-indigo-700">
              {z.name}
              <button onClick={() => removeZone(z.id)} className="text-indigo-400 hover:text-red-600"><Trash2 size={13} /></button>
            </span>
          ))}
          {zones.length === 0 && <span className="text-sm text-slate-400">No zones yet</span>}
        </div>
      </Card>

      <h2 className="mb-3 text-sm font-semibold text-slate-500">DRIVER COVERAGE</h2>
      {drivers.length === 0 ? (
        <Card className="p-6 text-center text-slate-400">No drivers yet. Add drivers in Team &amp; Access.</Card>
      ) : (
        <div className="space-y-3">
          {drivers.map((d) => (
            <Card key={d.id} className="p-5">
              <div className="mb-3 font-medium">{d.full_name || d.email}</div>
              <div className="flex flex-wrap gap-2">
                {zones.map((z) => {
                  const on = (driverZones[d.id] || []).includes(z.id);
                  return (
                    <button key={z.id} onClick={() => toggleDriverZone(d.id, z.id)}
                      className={`rounded-full px-3 py-1 text-sm transition ${on ? "bg-[var(--primary)] text-white" : "bg-gray-100 text-slate-600 hover:bg-gray-200"}`}>
                      {z.name}
                    </button>
                  );
                })}
                {zones.length === 0 && <span className="text-sm text-slate-400">Create zones first</span>}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}