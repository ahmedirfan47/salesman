"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ago, duration, JOB_LABEL, num, when, type SystemStatus } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { TableScroll } from "@/components/table-scroll";
import { CheckCircle2, Database, RefreshCcw, Server, Trash2, XCircle } from "lucide-react";

export default function SystemPage() {
  const [data, setData] = useState<SystemStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setError("");
    api("/platform/system").then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function job(id: string, action: "retry" | "discard") {
    setBusy(id);
    setError("");
    try {
      await api(`/platform/jobs/${id}/${action}`, { method: "POST" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  if (!data) return error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-slate-400">Checking…</p>;
  const z = data.zatca.documents;
  const missing = data.config.filter((c) => !c.ok).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-500">Checked {when(data.checked_at)}.</p>
        <Button variant="outline" onClick={load}><RefreshCcw size={16} /> Check again</Button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><Server size={16} /> SERVER</h3>
          <Rows rows={[
            ["Environment", data.server.environment],
            ["Running for", duration(data.server.uptime_seconds)],
            ["Background jobs", data.server.worker_enabled ? "Run in this server" : "Off in this server"],
            ["Version", `Salesman ${data.server.version} · Python ${data.server.python}`],
          ]} />
        </Card>
        <Card className="p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><Database size={16} /> DATABASE</h3>
          {data.database.ok ? (
            <Rows rows={[
              ["Status", <Ok key="s" ok text="Answering" />],
              ["Response time", `${data.database.latency_ms} ms`],
              ["Size", `${data.database.size_mb} MB`],
              ["Postgres", data.database.version ?? "—"],
            ]} />
          ) : <p className="text-sm text-red-600">Not answering: {data.database.error}</p>}
        </Card>
      </div>

      <Card className="p-5">
        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <h3 className="text-sm font-semibold text-slate-500">BACKGROUND JOBS</h3>
          <span className={`text-sm ${data.jobs.oldest_waiting_seconds > 300 ? "text-amber-700" : "text-slate-500"}`}>
            {data.jobs.oldest_waiting_seconds ? `Oldest waiting: ${duration(data.jobs.oldest_waiting_seconds)}` : "Nothing waiting"}
          </span>
        </div>
        <TableScroll>
          <table className="w-full min-w-[520px] text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-2 pr-3 font-medium">Job</th><th className="py-2 pr-3 text-right font-medium">Waiting</th>
                <th className="py-2 pr-3 text-right font-medium">Running</th><th className="py-2 pr-3 text-right font-medium">Done 24 h</th>
                <th className="py-2 text-right font-medium">Failed</th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.kinds.map((k) => (
                <tr key={k.kind} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-3">{JOB_LABEL[k.kind] ?? k.kind}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{num(k.queued)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{num(k.running)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{num(k.done_24h)}</td>
                  <td className={`py-2 text-right tabular-nums ${k.failed ? "font-medium text-red-600" : ""}`}>{num(k.failed)}</td>
                </tr>
              ))}
              {data.jobs.kinds.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-400">No jobs in the last 24 hours</td></tr>}
            </tbody>
          </table>
        </TableScroll>

        {data.jobs.failed.length > 0 && (
          <>
            <h4 className="mb-2 mt-5 text-sm font-semibold">Failed jobs</h4>
            <ul className="space-y-2">
              {data.jobs.failed.map((j) => (
                <li key={j.id} className="rounded-lg border border-[var(--border)] p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{JOB_LABEL[j.kind] ?? j.kind}{j.business && <span className="font-normal text-slate-500"> · {j.business}</span>}</div>
                      <div className="text-xs text-slate-400">{j.attempts} of {j.max_attempts} tries · failed {ago(j.finished_at)}</div>
                      <div className="mt-1 break-words font-mono text-xs text-red-700">{j.last_error}</div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button variant="outline" className="px-2 py-1 text-xs" disabled={busy === j.id} onClick={() => job(j.id, "retry")}>
                        <RefreshCcw size={14} /> Retry
                      </Button>
                      <Button variant="ghost" className="px-2 py-1 text-xs text-slate-500" disabled={busy === j.id} onClick={() => job(j.id, "discard")}>
                        <Trash2 size={14} /> Discard
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold text-slate-500">WHATSAPP</h3>
          <Rows rows={[
            ["Branches connected", `${num(data.whatsapp.connected)} of ${num(data.whatsapp.branches)}`],
            ["Messages in, last 24 h", num(data.whatsapp.messages_in_24h)],
            ["Messages out, last 24 h", num(data.whatsapp.messages_out_24h)],
            ["Last message from a customer", ago(data.whatsapp.last_inbound_at)],
          ]} />
        </Card>
        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold text-slate-500">ZATCA E-INVOICING</h3>
          <Rows rows={[
            ["Branches connected", num(data.zatca.units.active ?? 0)],
            ["Cleared and reported", num(z.cleared + z.reported)],
            ["Waiting to send", num(z.queued)],
            ["Rejected or blocked", <span key="r" className={z.rejected + z.blocked ? "font-medium text-red-600" : ""}>{num(z.rejected + z.blocked)}</span>],
          ]} />
          {data.zatca.expiring.map((e) => (
            <p key={`${e.business}-${e.branch}`} className="mt-2 text-sm text-amber-800">
              {e.business}, {e.branch}: certificate ({e.environment}) expires {when(e.expires_at)}
            </p>
          ))}
        </Card>
      </div>

      <Card className="p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-500">ERP CONNECTIONS</h3>
        {data.erp.length === 0 ? <p className="text-sm text-slate-400">No business has connected an ERP yet.</p> : (
          <TableScroll>
            <table className="w-full min-w-[620px] text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr>
                  <th className="py-2 pr-3 font-medium">Business</th><th className="py-2 pr-3 font-medium">System</th>
                  <th className="py-2 pr-3 font-medium">Status</th><th className="py-2 pr-3 font-medium">Last fetch</th>
                  <th className="py-2 text-right font-medium">Failed 7 days</th>
                </tr>
              </thead>
              <tbody>
                {data.erp.map((c) => (
                  <tr key={c.business} className="border-t border-[var(--border)] align-top">
                    <td className="py-2 pr-3 font-medium">{c.business}</td>
                    <td className="py-2 pr-3 capitalize">{c.provider} {c.server_version}</td>
                    <td className="py-2 pr-3 capitalize">{c.status}{c.last_error && <span className="block text-xs normal-case text-red-600">{c.last_error}</span>}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-slate-500">{ago(c.last_pull_at)}</td>
                    <td className={`py-2 text-right tabular-nums ${c.failed_7d ? "font-medium text-red-600" : ""}`}>{num(c.failed_7d)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Card>

      <Card className="p-5">
        <h3 className="mb-1 text-sm font-semibold text-slate-500">CONFIGURATION</h3>
        <p className="mb-3 text-sm text-slate-500">
          {missing ? `${missing} setting${missing === 1 ? "" : "s"} to look at.` : "Everything is set."} Values are never shown here, only whether each one is set.
        </p>
        <ul className="divide-y divide-[var(--border)]">
          {data.config.map((c) => (
            <li key={c.key} className="flex items-start gap-3 py-2">
              <Ok ok={c.ok} />
              <div className="min-w-0">
                <div className="font-mono text-xs font-medium">{c.key}</div>
                <div className="text-sm text-slate-500">{c.note}</div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="space-y-1.5 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-3">
          <dt className="text-slate-500">{label}</dt>
          <dd className="text-right font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Ok({ ok, text }: { ok: boolean; text?: string }) {
  return ok
    ? <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 size={16} className="shrink-0" />{text}</span>
    : <span className="inline-flex items-center gap-1 text-amber-600"><XCircle size={16} className="shrink-0" />{text}</span>;
}