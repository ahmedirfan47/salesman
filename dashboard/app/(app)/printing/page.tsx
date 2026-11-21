"use client";

import { useEffect, useState } from "react";
import { api, getToken, isDemo } from "@/lib/api";
import { useMe } from "@/lib/use-me";
import { useBranches } from "@/lib/branches";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Copy, FileText, MonitorSmartphone, Plus, Printer, RefreshCcw, Trash2 } from "lucide-react";
import { TableScroll } from "@/components/table-scroll";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type PrintJob = {
  id: string;
  status: string;
  payload: { order_number?: string; customer_name?: string; total_amount?: number; currency?: string };
  error: string | null;
  attempts?: number;
  printed_at: string | null;
  created_at: string;
};

type Agent = {
  id: string; name: string; branch_id: string; branch_name: string | null; key_prefix: string; printer: string | null;
  version: string | null; last_seen_at: string | null; online: boolean; revoked: boolean; created_at: string;
};

const statusColor: Record<string, string> = {
  queued: "bg-amber-50 text-amber-700",
  printing: "bg-blue-50 text-blue-700",
  done: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-700",
};

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never");

export default function PrintingPage() {
  const { me } = useMe();
  const isAdmin = me?.role === "owner" || me?.role === "admin";
  const [jobs, setJobs] = useState<PrintJob[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    api("/printing/jobs").then(setJobs).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  function viewSlip(id: string) {
    if (isDemo()) {
      setError("Downloads aren't available in the demo.");
      return;
    }
    fetch(`${API_BASE}/api/v1/printing/jobs/${id}/slip.pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => r.blob())
      .then((b) => window.open(URL.createObjectURL(b), "_blank"));
  }

  async function retry(id: string) {
    setBusy(id);
    setError("");
    try {
      await api(`/printing/jobs/${id}/retry`, { method: "POST" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-2xl font-bold">Print Queue</h1>
      <p className="mb-6 text-sm text-slate-500">Order slips waiting to print, the print agents at your branches, and print history</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <Agents isAdmin={isAdmin} />

      <h2 className="mb-3 mt-8 text-sm font-semibold text-slate-500">SLIPS</h2>
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Order</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-[var(--border)] last:border-0 align-top">
                  <td className="px-4 py-3 font-mono text-xs">{j.payload.order_number ?? "—"}</td>
                  <td className="px-4 py-3">{j.payload.customer_name ?? "—"}</td>
                  <td className="px-4 py-3">
                    {j.payload.currency} {j.payload.total_amount?.toLocaleString() ?? ""}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${statusColor[j.status] ?? "bg-gray-100"}`}>{j.status}</span>
                    {j.error && <div className="mt-1 max-w-xs text-xs text-red-600">{j.error}</div>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      {(j.status === "failed" || j.status === "done") && (
                        <Button variant="outline" disabled={busy === j.id} onClick={() => retry(j.id)}>
                          <RefreshCcw size={14} /> Print again
                        </Button>
                      )}
                      <Button variant="outline" onClick={() => viewSlip(j.id)}>
                        <FileText size={14} /> Slip
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {jobs.length === 0 && !error && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-slate-400">
                    <Printer size={24} className="mx-auto mb-2 opacity-40" />
                    No print jobs yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </div>
  );
}

function Agents({ isAdmin }: { isAdmin: boolean }) {
  const { branches } = useBranches();
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [form, setForm] = useState({ name: "", branch_id: "" });
  const [adding, setAdding] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api("/printing/agents").then(setAgents).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function create() {
    setBusy(true);
    setError("");
    try {
      const r = await api("/printing/agents", {
        method: "POST",
        body: JSON.stringify({ name: form.name.trim() || "Warehouse printer", branch_id: form.branch_id || branches[0]?.id }),
      });
      setKey(r.key);
      setAdding(false);
      setForm({ name: "", branch_id: "" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(a: Agent) {
    if (!window.confirm(`Revoke "${a.name}"? It stops printing at once; its unprinted slips go back to the queue.`)) return;
    try {
      await api(`/printing/agents/${a.id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-500">PRINT AGENTS</h2>
        {isAdmin && !adding && (
          <Button variant="outline" onClick={() => { setAdding(true); setKey(null); }}><Plus size={14} /> Add agent</Button>
        )}
      </div>
      <p className="mb-3 text-sm text-slate-500">
        A print agent is a small program on a PC at the warehouse. It prints every new slip for its branch within seconds and
        needs no firewall changes. Download it from the <code className="rounded bg-gray-100 px-1">print-agent</code> folder of
        the Salesman repository and follow its README.
      </p>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      {key && (
        <Card className="mb-3 border-emerald-200 bg-emerald-50/60 p-4">
          <p className="text-sm font-medium text-emerald-900">Copy this key into the agent&apos;s config.ini now. It won&apos;t be shown again.</p>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <code className="flex-1 break-all rounded-lg bg-white px-3 py-2 font-mono text-xs">{key}</code>
            <Button variant="outline" onClick={() => { navigator.clipboard?.writeText(key); setCopied(true); }}>
              <Copy size={14} /> {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </Card>
      )}

      {adding && (
        <Card className="mb-3 p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="text-xs font-medium text-slate-500">Name
              <Input className="mt-1" placeholder="Riyadh dock PC" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">Branch
              <select className="mt-1 w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm" value={form.branch_id}
                onChange={(e) => setForm({ ...form, branch_id: e.target.value })}>
                {branches.filter((b) => b.is_active).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
            <div className="flex items-end gap-2">
              <Button disabled={busy} onClick={create}>Create</Button>
              <Button variant="outline" onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {(agents ?? []).map((a) => (
          <Card key={a.id} className={`p-4 ${a.revoked ? "opacity-60" : ""}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <MonitorSmartphone size={16} className="text-slate-400" />
                  <span className="font-semibold">{a.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${a.revoked ? "bg-gray-100 text-slate-500" : a.online ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>
                    {a.revoked ? "Revoked" : a.online ? "Online" : "Offline"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{a.branch_name} · {a.printer ?? "printer not reported yet"}{a.version ? ` · v${a.version}` : ""}</p>
                <p className="text-xs text-slate-400">Last seen {when(a.last_seen_at)} · key {a.key_prefix}…</p>
              </div>
              {isAdmin && !a.revoked && (
                <button type="button" aria-label="Revoke" className="text-slate-400 hover:text-red-600" onClick={() => revoke(a)}>
                  <Trash2 size={16} />
                </button>
              )}
            </div>
          </Card>
        ))}
        {agents?.length === 0 && (
          <Card className="p-4 text-sm text-slate-400 sm:col-span-2">
            No print agents yet. Slips can still be opened and printed from this page.
          </Card>
        )}
      </div>
    </section>
  );
}
