"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ShieldAlert, UserPlus } from "lucide-react";
import { TableScroll } from "@/components/table-scroll";

type Zone = { id: string; name: string };
type Customer = {
  id: string; name: string; company: string | null;
  whatsapp_number: string | null; address: string | null;
  zone_id: string | null; is_active: boolean;
};

export default function CustomersPage() {
  const { me, loading } = useMe();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [zones, setZones] = useState<Zone[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", company: "", whatsapp_number: "", address: "", zone_id: "" });

  function load() {
    Promise.all([api("/customers"), api("/zones")])
      .then(([c, z]) => { setCustomers(c); setZones(z); })
      .catch((e) => setError(e.message));
  }
  useEffect(() => { if (can(me, "manage_users")) load(); }, [me]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!can(me, "manage_users")) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Admins only</h1>
        <p className="mt-2 text-sm text-slate-500">Managing customers is an admin task.</p>
      </Card>
    );
  }

  async function addCustomer() {
    if (!form.name.trim()) return;
    setBusy(true); setError(""); setMsg("");
    try {
      await api("/customers", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          company: form.company || null,
          whatsapp_number: form.whatsapp_number || null,
          address: form.address || null,
          zone_id: form.zone_id || null,
        }),
      });
      setMsg(`Added ${form.name}.`);
      setForm({ name: "", company: "", whatsapp_number: "", address: "", zone_id: "" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function changeZone(id: string, zone_id: string) {
    try { await api(`/customers/${id}`, { method: "PATCH", body: JSON.stringify({ zone_id: zone_id || null }) }); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Customers</h1>
      <p className="mb-6 text-sm text-slate-500">Add customers once with their delivery zone — orders then route automatically</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      <Card className="mb-6 p-6">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-500"><UserPlus size={16} /> ADD CUSTOMER</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Input placeholder="Name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input placeholder="Company" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
          <Input placeholder="WhatsApp (+966…)" value={form.whatsapp_number} onChange={(e) => setForm({ ...form, whatsapp_number: e.target.value })} />
          <Input placeholder="Address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="sm:col-span-2" />
          <select value={form.zone_id} onChange={(e) => setForm({ ...form, zone_id: e.target.value })}
            className="rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm">
            <option value="">No zone</option>
            {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
          </select>
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={addCustomer} disabled={busy || !form.name.trim()}>{busy ? "Adding…" : "Add customer"}</Button>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[600px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Company</th>
                <th className="px-4 py-3 font-medium">WhatsApp</th>
                <th className="px-4 py-3 font-medium">Zone</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => (
                <tr key={c.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3 text-slate-600">{c.company ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{c.whatsapp_number ?? "—"}</td>
                  <td className="px-4 py-3">
                    <select value={c.zone_id ?? ""} onChange={(e) => changeZone(c.id, e.target.value)}
                      className="rounded-lg border border-[var(--border)] bg-white px-2 py-1 text-xs">
                      <option value="">No zone</option>
                      {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
              {customers.length === 0 && !error && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No customers yet</td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </div>
  );
}