"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ago, CLIENT_LABEL, num, SIGN_IN_REASON, when, type BusinessDetail, type BusinessRow } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { Ban, CheckCircle2, Search, X } from "lucide-react";

export default function BusinessesPage() {
  const [rows, setRows] = useState<BusinessRow[] | null>(null);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api("/platform/businesses").then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    load();
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) setSelected(id);
  }, [load]);

  const term = q.trim().toLowerCase();
  const shown = (rows ?? []).filter((b) => !term || b.name.toLowerCase().includes(term) || (b.owner_email ?? "").includes(term));

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-500">{rows ? `${rows.length} businesses on Salesman.` : "Every business on Salesman."}</p>
        <div className="relative sm:w-72">
          <Search size={16} className="absolute left-3 top-2.5 text-slate-400" />
          <Input className="pl-9" placeholder="Search by name or owner email" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Business</th>
                <th className="px-4 py-3 text-right font-medium">People</th>
                <th className="px-4 py-3 text-right font-medium">Active 7 days</th>
                <th className="px-4 py-3 text-right font-medium">Branches</th>
                <th className="px-4 py-3 text-right font-medium">Orders 30 days</th>
                <th className="px-4 py-3 font-medium">Last active</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((b) => (
                <tr key={b.id} onClick={() => setSelected(b.id)}
                  className={`cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-gray-50 ${selected === b.id ? "bg-indigo-50/50" : ""}`}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{b.name}</div>
                    <div className="text-xs text-slate-400">{b.owner_email ?? "No owner"} · since {new Date(b.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{num(b.people)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{num(b.active_people_7d)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{num(b.branches)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{num(b.orders_30d)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{ago(b.last_active_at)}</td>
                  <td className="px-4 py-3">
                    {b.suspended_at
                      ? <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Suspended</span>
                      : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>}
                  </td>
                </tr>
              ))}
              {rows === null && !error && <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
              {rows !== null && shown.length === 0 && <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">No businesses found</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>

      {selected && <BusinessPanel key={selected} id={selected} onChanged={load} onClose={() => setSelected(null)} />}
    </div>
  );
}

function BusinessPanel({ id, onChanged, onClose }: { id: string; onChanged: () => void; onClose: () => void }) {
  const [b, setB] = useState<BusinessDetail | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  // the panel opens below the list: bring it into view (on a phone it is off screen)
  useEffect(() => { panel.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/platform/businesses/${id}`).then(setB).catch((e) => setError(e.message));
  }, [id]);

  async function act(path: string, body?: object) {
    setBusy(true);
    setError("");
    try {
      setB(await api(`/platform/businesses/${id}/${path}`, { method: "POST", body: body ? JSON.stringify(body) : undefined }));
      setConfirm(false);
      setReason("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (!b) return <div ref={panel}><Card className="p-5">{error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-sm text-slate-400">Loading…</p>}</Card></div>;

  return (
    <div ref={panel} className="scroll-mt-4">
      <Card className="p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">{b.name}</h2>
            <p className="text-xs text-slate-400">{b.slug} · {b.timezone} · since {when(b.created_at)}</p>
          </div>
          <button aria-label="Close" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-700"><X size={18} /></button>
        </div>

        {b.suspended_at && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">
            Suspended {when(b.suspended_at)}: {b.suspended_reason}. Nobody here can sign in; their WhatsApp agent keeps answering customers.
          </div>
        )}

        <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {([
            ["Customers", b.counts.customers], ["Products", b.counts.products], ["Orders", b.counts.orders],
            ["Orders 30 days", b.counts.orders_30d], ["Invoices", b.counts.invoices], ["Conversations", b.counts.conversations],
          ] as [string, number][]).map(([label, value]) => (
            <div key={label} className="rounded-lg bg-gray-50 p-3">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
              <div className="mt-0.5 text-lg font-bold tabular-nums">{num(value)}</div>
            </div>
          ))}
        </div>

        <h3 className="mb-2 text-sm font-semibold">People</h3>
        <TableScroll>
          <table className="mb-5 w-full min-w-[620px] text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-2 pr-3 font-medium">Person</th><th className="py-2 pr-3 font-medium">Role</th>
                <th className="py-2 pr-3 font-medium">Branch</th><th className="py-2 pr-3 font-medium">Last seen</th><th className="py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {b.people.map((p) => (
                <tr key={p.id} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-3">
                    <div className={p.is_active ? "font-medium" : "font-medium text-slate-400 line-through"}>{p.full_name || p.email}</div>
                    {p.full_name && <div className="text-xs text-slate-400">{p.email}</div>}
                  </td>
                  <td className="py-2 pr-3 capitalize">{p.role}</td>
                  <td className="py-2 pr-3 text-slate-500">{p.branch ?? "All branches"}</td>
                  <td className="whitespace-nowrap py-2 pr-3 text-slate-500">{ago(p.last_seen_at)}</td>
                  <td className="py-2 text-right">
                    <Link href={`/platform/people?q=${encodeURIComponent(p.email)}`} className="text-xs font-medium text-[var(--primary)] hover:underline">Manage</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>

        <h3 className="mb-2 text-sm font-semibold">Branches and connections</h3>
        <TableScroll>
          <table className="mb-3 w-full min-w-[560px] text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-2 pr-3 font-medium">Branch</th><th className="py-2 pr-3 font-medium">WhatsApp</th><th className="py-2 font-medium">ZATCA</th></tr>
            </thead>
            <tbody>
              {b.branches.map((br) => (
                <tr key={br.id} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-3">
                    <span className={br.is_active ? "font-medium" : "font-medium text-slate-400"}>{br.name}</span>
                    {br.is_default && <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-500">Default</span>}
                    {!br.is_active && <span className="ml-2 text-xs text-slate-400">inactive</span>}
                  </td>
                  <td className="py-2 pr-3">{br.whatsapp_connected ? <span className="text-emerald-700">{br.whatsapp_number || "Connected"}</span> : <span className="text-slate-400">Not connected</span>}</td>
                  <td className="py-2 capitalize">{br.zatca ? `${br.zatca} (${br.zatca_environment})` : <span className="normal-case text-slate-400">Not connected</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
        <p className="mb-5 text-sm text-slate-600">
          ERP: {b.erp ? <>{b.erp.provider} {b.erp.server_version ?? ""}, <span className="font-medium">{b.erp.status}</span>, last fetched {ago(b.erp.last_pull_at)}
            {b.erp.last_error && <span className="block text-red-600">{b.erp.last_error}</span>}</> : <span className="text-slate-400">not connected</span>}
        </p>

        <h3 className="mb-2 text-sm font-semibold">Recent sign-ins</h3>
        {b.sign_ins.length === 0 ? <p className="mb-5 text-sm text-slate-400">None yet</p> : (
          <ul className="mb-5 space-y-1 text-sm">
            {b.sign_ins.map((s) => (
              <li key={s.id} className="flex flex-wrap gap-x-3 text-slate-600">
                <span className="whitespace-nowrap text-slate-400">{when(s.at)}</span>
                <span>{s.email}</span>
                <span className="text-slate-400">{CLIENT_LABEL[s.client] ?? s.client}</span>
                <span className={s.success ? "text-emerald-700" : "text-red-600"}>{SIGN_IN_REASON[s.reason] ?? s.reason}</span>
              </li>
            ))}
          </ul>
        )}

        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
        <div className="border-t border-[var(--border)] pt-4">
          {b.suspended_at ? (
            <Button disabled={busy} onClick={() => act("reactivate")}><CheckCircle2 size={16} /> Reactivate business</Button>
          ) : confirm ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Input placeholder="Reason (shown in the activity log)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <Button variant="danger" disabled={busy || reason.trim().length < 3} onClick={() => act("suspend", { reason })}>Suspend</Button>
              <Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button>
            </div>
          ) : (
            <Button variant="outline" className="text-red-700" onClick={() => setConfirm(true)}><Ban size={16} /> Suspend business</Button>
          )}
        </div>
      </Card>
    </div>
  );
}