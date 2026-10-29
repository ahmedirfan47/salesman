"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useMe } from "@/lib/use-me";
import { ago, ROLES, when, type Person } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { KeyRound, LogOut, Power, Search, ShieldCheck, X } from "lucide-react";

const select = "rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";
type State = "" | "active" | "inactive" | "online";

export default function PeoplePage() {
  const { me } = useMe();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [state, setState] = useState<State>("");
  const [rows, setRows] = useState<Person[] | null>(null);
  const [selected, setSelected] = useState<Person | null>(null);
  const [error, setError] = useState("");

  const load = useCallback((query: string, r: string, st: State) => {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (r) params.set("role", r);
    if (st) params.set("state", st);
    api(`/platform/people?${params}`).then(setRows).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setQ(new URLSearchParams(window.location.search).get("q") ?? "");
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(q, role, state), 300);
    return () => clearTimeout(t);
  }, [q, role, state, load]);

  function changed(p: Person) {
    setSelected(p);
    setRows((rs) => rs?.map((r) => (r.id === p.id ? p : r)) ?? null);
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-2.5 text-slate-400" />
          <Input className="pl-9" placeholder="Search by name, email or business" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className={select} value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
          <option value="">All roles</option>
          {[...ROLES, "demo"].map((r) => <option key={r} value={r} className="capitalize">{r}</option>)}
        </select>
        <select className={select} value={state} onChange={(e) => setState(e.target.value as State)} aria-label="Status">
          <option value="">Everyone</option>
          <option value="online">Online now</option>
          <option value="active">Active accounts</option>
          <option value="inactive">Switched off</option>
        </select>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Person</th>
                <th className="px-4 py-3 font-medium">Business</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Last seen</th>
                <th className="px-4 py-3 font-medium">Last sign-in</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((p) => (
                <tr key={p.id} onClick={() => setSelected(p)}
                  className={`cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-gray-50 ${selected?.id === p.id ? "bg-indigo-50/50" : ""}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5 font-medium">
                      {p.full_name || p.email}
                      {p.is_platform_admin && <ShieldCheck size={14} className="text-[var(--primary)]" aria-label="Stonic admin" />}
                    </div>
                    {p.full_name && <div className="text-xs text-slate-400">{p.email}</div>}
                  </td>
                  <td className="px-4 py-3">{p.business}</td>
                  <td className="px-4 py-3 capitalize">{p.role}{p.branch && <span className="block text-xs normal-case text-slate-400">{p.branch}</span>}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{ago(p.last_seen_at)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{ago(p.last_login_at)}</td>
                  <td className="px-4 py-3">
                    {p.is_active
                      ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                      : <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-500">Switched off</span>}
                  </td>
                </tr>
              ))}
              {rows === null && !error && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
              {rows?.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Nobody found</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>

      {selected && (
        <PersonPanel key={selected.id} person={selected} isMe={selected.id === me?.id} onChanged={changed} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function PersonPanel({ person: p, isMe, onChanged, onClose }: {
  person: Person; isMe: boolean; onChanged: (p: Person) => void; onClose: () => void;
}) {
  const [role, setRole] = useState(p.role);
  const panel = useRef<HTMLDivElement>(null);
  // the panel opens below the list: bring it into view (on a phone it is off screen)
  useEffect(() => { panel.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function run(path: string, method: string, body: object | undefined, done: string) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      onChanged(await api(`/platform/people/${p.id}${path}`, { method, body: body ? JSON.stringify(body) : undefined }));
      setMsg(done);
      setPassword("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={panel} className="scroll-mt-4">
      <Card className="p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">{p.full_name || p.email}</h2>
            <p className="break-all text-sm text-slate-500">{p.email} · {p.business}</p>
            <p className="text-xs text-slate-400">
              Added {when(p.created_at)} · last signed in {when(p.last_login_at)} · last seen {when(p.last_seen_at)}
            </p>
          </div>
          <button aria-label="Close" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700"><X size={18} /></button>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <label className="text-xs font-medium text-slate-500">Role</label>
            <div className="mt-1 flex gap-2">
              <select className={`${select} flex-1 capitalize`} value={role} onChange={(e) => setRole(e.target.value)} disabled={p.role === "demo"}>
                {(p.role === "demo" ? ["demo"] : ROLES).map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
              <Button variant="outline" disabled={busy || role === p.role} onClick={() => run("", "PATCH", { role }, "Role changed.")}>Save</Button>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500">New password</label>
            <div className="mt-1 flex gap-2">
              <Input type="password" autoComplete="new-password" placeholder="At least 8 characters" value={password}
                onChange={(e) => setPassword(e.target.value)} />
              <Button variant="outline" disabled={busy || password.length < 8}
                onClick={() => run("/password", "POST", { password }, isMe ? "Password changed." : "Password set. Their other sessions have ended.")}>
                <KeyRound size={16} /> Set
              </Button>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500">Access</label>
            <div className="mt-1 flex flex-wrap gap-2">
              {!isMe && (
                <Button variant="outline" disabled={busy} className={p.is_active ? "text-red-700" : ""}
                  onClick={() => run("", "PATCH", { is_active: !p.is_active }, p.is_active ? "Switched off. They can't sign in." : "Switched on.")}>
                  <Power size={16} /> {p.is_active ? "Switch off" : "Switch on"}
                </Button>
              )}
              {!isMe && (
                <Button variant="outline" disabled={busy} onClick={() => run("/sign-out", "POST", undefined, "Signed out on every device.")}>
                  <LogOut size={16} /> Sign out everywhere
                </Button>
              )}
              {isMe && <p className="text-sm text-slate-400">This is you.</p>}
            </div>
          </div>
        </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        {msg && <p className="mt-3 text-sm text-emerald-700">{msg}</p>}
      </Card>
    </div>
  );
}