"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UserPlus, ShieldAlert } from "lucide-react";
import { TableScroll } from "@/components/table-scroll";

type User = {
  id: string; email: string; full_name: string | null;
  role: string; is_active: boolean;
};

const ROLES = ["admin", "salesman", "dispatcher", "driver", "warehouse", "viewer"];

const roleColor: Record<string, string> = {
  owner: "bg-purple-50 text-purple-700",
  admin: "bg-indigo-50 text-indigo-700",
  salesman: "bg-emerald-50 text-emerald-700",
  dispatcher: "bg-blue-50 text-blue-700",
  driver: "bg-amber-50 text-amber-700",
  warehouse: "bg-cyan-50 text-cyan-700",
  viewer: "bg-gray-100 text-gray-600",
};

export default function AdminPage() {
  const { me, loading } = useMe();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "salesman" });
  const [busy, setBusy] = useState(false);

  function load() {
    api("/users").then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(() => {
    if (can(me, "manage_users")) load();
  }, [me]);

  if (loading) return <p className="text-slate-400">Loading…</p>;

  if (!can(me, "manage_users")) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Admins only</h1>
        <p className="mt-2 text-sm text-slate-500">Your role ({me?.role}) doesn't have access to user management.</p>
      </Card>
    );
  }

  async function createUser() {
    setError(""); setMsg(""); setBusy(true);
    try {
      await api("/users", { method: "POST", body: JSON.stringify(form) });
      setMsg(`Created ${form.email} as ${form.role}.`);
      setForm({ full_name: "", email: "", password: "", role: "salesman" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(id: string, role: string) {
    try { await api(`/users/${id}`, { method: "PATCH", body: JSON.stringify({ role }) }); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }
  async function toggleActive(id: string, is_active: boolean) {
    try { await api(`/users/${id}`, { method: "PATCH", body: JSON.stringify({ is_active }) }); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Team & Access</h1>
      <p className="mb-6 text-sm text-slate-500">Add team members and control what each role can do</p>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      <Card className="mb-6 p-6">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-500">
          <UserPlus size={16} /> ADD TEAM MEMBER
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input placeholder="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input type="password" placeholder="Password (8+ chars)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
            className="rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--primary)]">
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={createUser} disabled={busy || !form.email || !form.password}>
            {busy ? "Adding…" : "Add member"}
          </Button>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isOwner = u.role === "owner";
                const isSelf = u.id === me?.id;
                return (
                  <tr key={u.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3">{u.full_name ?? "—"}{isSelf && <span className="ml-2 text-xs text-slate-400">(you)</span>}</td>
                    <td className="px-4 py-3 text-slate-600">{u.email}</td>
                    <td className="px-4 py-3">
                      {isOwner ? (
                        <span className={`rounded-full px-2 py-0.5 text-xs ${roleColor.owner}`}>owner</span>
                      ) : (
                        <select value={u.role} onChange={(e) => changeRole(u.id, e.target.value)}
                          className={`rounded-full px-2 py-1 text-xs ${roleColor[u.role] ?? "bg-gray-100"}`}>
                          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${u.is_active ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
                        {u.is_active ? "Active" : "Disabled"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!isOwner && !isSelf && (
                        <Button variant="outline" onClick={() => toggleActive(u.id, !u.is_active)}>
                          {u.is_active ? "Disable" : "Enable"}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </div>
  );
}