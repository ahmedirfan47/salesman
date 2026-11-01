"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { KeyRound, Plus, Power, X } from "lucide-react";
import { consoleApi, setAdminToken, type Admin } from "@/lib/console-api";
import { useAdmin } from "@/lib/use-admin";
import { ago, when } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";

const MIN_PASSWORD = 10;

export default function AdminsPage() {
  const { admin: me } = useAdmin();
  const [rows, setRows] = useState<Admin[] | null>(null);
  const [selected, setSelected] = useState<Admin | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    consoleApi("/platform/admins").then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  function changed(a: Admin) {
    setSelected(a);
    setRows((rs) => (rs ?? []).map((r) => (r.id === a.id ? a : r)));
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-500">
          Admins are not part of any business and can&apos;t sign in to the dashboard or the app with these accounts.
        </p>
        {!adding && (
          <Button onClick={() => { setAdding(true); setSelected(null); }} className="shrink-0"><Plus size={16} /> Add admin</Button>
        )}
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {adding && (
        <AddAdmin onClose={() => setAdding(false)} onAdded={(a) => { setRows((rs) => [...(rs ?? []), a]); setAdding(false); }} />
      )}

      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Admin</th>
                <th className="px-4 py-3 font-medium">Added</th>
                <th className="px-4 py-3 font-medium">Last seen</th>
                <th className="px-4 py-3 font-medium">Last sign-in</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((a) => (
                <tr key={a.id} onClick={() => { setSelected(a); setAdding(false); }}
                  className={`cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-gray-50 ${selected?.id === a.id ? "bg-indigo-50/50" : ""}`}>
                  <td className="px-4 py-3">
                    <div className="font-medium">
                      {a.full_name || a.email}
                      {a.id === me.id && <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-normal text-[var(--primary)]">You</span>}
                    </div>
                    {a.full_name && <div className="text-xs text-slate-400">{a.email}</div>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{when(a.created_at)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{ago(a.last_seen_at)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{ago(a.last_login_at)}</td>
                  <td className="px-4 py-3">
                    {a.is_active
                      ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                      : <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-500">Switched off</span>}
                  </td>
                </tr>
              ))}
              {rows === null && !error && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>

      {selected && (
        <AdminPanel key={selected.id} target={selected} isMe={selected.id === me.id} onChanged={changed} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function AddAdmin({ onAdded, onClose }: { onAdded: (a: Admin) => void; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onAdded(await consoleApi("/platform/admins", {
        method: "POST", body: JSON.stringify({ email, password, full_name: name || null }),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6 p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Add an admin</h2>
          <p className="text-sm text-slate-500">They get full access to this console. Give them the password yourself.</p>
        </div>
        <button aria-label="Close" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700"><X size={18} /></button>
      </div>
      <form onSubmit={submit} className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label className="text-xs font-medium text-slate-500">Email</label>
          <Input className="mt-1" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="text-xs font-medium text-slate-500">Name (optional)</label>
          <Input className="mt-1" value={name} maxLength={255} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="text-xs font-medium text-slate-500">Password</label>
          <Input className="mt-1" type="password" autoComplete="new-password" placeholder={`At least ${MIN_PASSWORD} characters`}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="md:col-span-3">
          <Button type="submit" disabled={busy || !email || password.length < MIN_PASSWORD}>
            {busy ? "Adding…" : "Add admin"}
          </Button>
        </div>
      </form>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
    </Card>
  );
}

function AdminPanel({ target: a, isMe, onChanged, onClose }: {
  target: Admin; isMe: boolean; onChanged: (a: Admin) => void; onClose: () => void;
}) {
  const { setAdmin } = useAdmin();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { panel.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  const [name, setName] = useState(a.full_name ?? "");
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function run(task: () => Promise<void>, done: string) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await task();
      setMsg(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const update = (body: object) => async () => {
    const updated: Admin = await consoleApi(`/platform/admins/${a.id}`, { method: "PATCH", body: JSON.stringify(body) });
    onChanged(updated);
    if (isMe) setAdmin(updated);
  };

  const setNewPassword = async () => {
    const r = await consoleApi(`/platform/admins/${a.id}/password`, {
      method: "POST", body: JSON.stringify({ password, current_password: isMe ? current : null }),
    });
    if (r.access_token) setAdminToken(r.access_token); // your own: stay signed in here
    onChanged(r.admin);
    setPassword("");
    setCurrent("");
  };

  return (
    <div ref={panel} className="scroll-mt-4">
      <Card className="p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">{a.full_name || a.email}</h2>
            <p className="break-all text-sm text-slate-500">{a.email}</p>
            <p className="text-xs text-slate-400">
              Added {when(a.created_at)} · last signed in {when(a.last_login_at)} · last seen {when(a.last_seen_at)}
            </p>
          </div>
          <button aria-label="Close" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700"><X size={18} /></button>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <label className="text-xs font-medium text-slate-500">Name</label>
            <div className="mt-1 flex gap-2">
              <Input value={name} maxLength={255} onChange={(e) => setName(e.target.value)} />
              <Button variant="outline" disabled={busy || name.trim() === (a.full_name ?? "")}
                onClick={() => run(update({ full_name: name }), "Name saved.")}>Save</Button>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500">{isMe ? "Change your password" : "New password"}</label>
            <div className="mt-1 space-y-2">
              {isMe && (
                <Input type="password" autoComplete="current-password" placeholder="Current password" value={current}
                  onChange={(e) => setCurrent(e.target.value)} />
              )}
              <div className="flex gap-2">
                <Input type="password" autoComplete="new-password" placeholder={`At least ${MIN_PASSWORD} characters`} value={password}
                  onChange={(e) => setPassword(e.target.value)} />
                <Button variant="outline" disabled={busy || password.length < MIN_PASSWORD || (isMe && !current)}
                  onClick={() => run(setNewPassword, isMe ? "Password changed. Your other sessions have ended." : "Password set. Their sessions have ended.")}>
                  <KeyRound size={16} /> Set
                </Button>
              </div>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500">Access</label>
            <div className="mt-1">
              {isMe ? (
                <p className="text-sm text-slate-400">This is you. Another admin can switch you off.</p>
              ) : (
                <Button variant="outline" disabled={busy} className={a.is_active ? "text-red-700" : ""}
                  onClick={() => run(update({ is_active: !a.is_active }), a.is_active ? "Switched off. They can't sign in." : "Switched on.")}>
                  <Power size={16} /> {a.is_active ? "Switch off" : "Switch on"}
                </Button>
              )}
            </div>
          </div>
        </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        {msg && <p className="mt-3 text-sm text-emerald-700">{msg}</p>}
      </Card>
    </div>
  );
}