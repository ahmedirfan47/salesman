"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { useBranches } from "@/lib/branches";
import {
  ACTION_LABEL, METHOD_LABEL, connectionBadge, statusBadge, when,
  type Balance, type Connection, type ConnectionSettings, type ConnectResult, type Options, type Overview, type SyncEvent,
} from "@/lib/integrations";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { AlertTriangle, Cable, Pause, Play, RefreshCcw, Scale, ShieldAlert, Unplug } from "lucide-react";

const select = "w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";

export default function IntegrationsPage() {
  const { me, loading } = useMe();
  const allowed = can(me, "manage_integrations");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [version, setVersion] = useState(0);

  const load = useCallback(() => {
    api("/integrations").then(setOverview).catch((e) => setError(e.message));
    setVersion((v) => v + 1);
  }, []);
  useEffect(() => { if (allowed) load(); }, [allowed, load]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!allowed) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">No access</h1>
        <p className="mt-2 text-sm text-slate-500">Only owners and admins can connect an ERP or accounting system.</p>
      </Card>
    );
  }

  const conn = overview?.connection ?? null;

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Cable size={22} /> Integrations</h1>
      <p className="mb-6 text-sm text-slate-500">
        Connect your ERP or accounting system. It keeps your products, prices and stock; Salesman sends it your customers,
        orders, invoices and payments.
      </p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {!overview && !error && <p className="text-slate-400">Loading…</p>}

      {overview && (!conn || editing) && (
        <ConnectCard providers={overview.providers} connection={conn} onCancel={conn ? () => setEditing(false) : undefined}
          onDone={() => { setEditing(false); load(); }} />
      )}

      {overview && conn && !editing && (
        <div className="space-y-6">
          <StatusCard connection={conn} problems={overview.problems} counts={overview.counts}
            onEdit={() => setEditing(true)} onChange={load} />
          <Mapping connection={conn} onSaved={load} />
          <Activity version={version} active={conn.status === "active"} onChange={load} />
          <Balances />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- connecting
function ConnectCard({ providers, connection, onDone, onCancel }: {
  providers: Overview["providers"]; connection: Connection | null; onDone: () => void; onCancel?: () => void;
}) {
  const [provider, setProvider] = useState(connection?.provider ?? "");
  const [f, setF] = useState({
    url: connection?.base_url ?? "", database: connection?.database ?? "", username: connection?.username ?? "", api_key: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function connect() {
    setBusy(true);
    setError("");
    try {
      await api("/integrations/connect", { method: "POST", body: JSON.stringify({ provider, ...f }) }) as ConnectResult;
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (!provider) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {providers.map((p) => (
          <Card key={p.key} className="flex items-center justify-between gap-3 p-5">
            <div>
              <div className="font-semibold">{p.name}</div>
              <div className="text-xs text-slate-500">{p.available ? "Products, prices and stock in; orders, invoices and payments out" : "Coming next"}</div>
            </div>
            {p.available
              ? <Button onClick={() => setProvider(p.key)}><Cable size={16} /> Connect</Button>
              : <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-500">Soon</span>}
          </Card>
        ))}
      </div>
    );
  }

  return (
    <Card className="p-5">
      <h2 className="mb-1 font-semibold">{connection ? "Connection details" : "Connect Odoo"}</h2>
      <p className="mb-4 text-sm text-slate-500">
        In Odoo, open your profile (top right) › <em>Preferences</em> or <em>My Profile</em> › <em>Account Security</em>,
        and create a new API key. Use a user who can manage sales, inventory and invoicing.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-slate-500">Odoo address
          <Input className="mt-1" placeholder="https://yourcompany.odoo.com" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
        </label>
        <label className="text-xs font-medium text-slate-500">Database
          <Input className="mt-1" placeholder="Usually the first part of the address" value={f.database}
            onChange={(e) => setF({ ...f, database: e.target.value })} />
        </label>
        <label className="text-xs font-medium text-slate-500">User login (email)
          <Input className="mt-1" placeholder="Needed for Odoo 18 and older" value={f.username}
            onChange={(e) => setF({ ...f, username: e.target.value })} />
        </label>
        <label className="text-xs font-medium text-slate-500">API key
          <Input className="mt-1" type="password" autoComplete="off" placeholder={connection ? "Leave empty to keep the saved key" : ""}
            value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })} />
        </label>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button disabled={busy || !f.url.trim() || (!connection && !f.api_key.trim())} onClick={connect}>
          <Cable size={16} /> {busy ? "Checking with Odoo…" : connection ? "Save and check" : "Connect"}
        </Button>
        <Button variant="outline" onClick={() => (onCancel ? onCancel() : setProvider(""))}>Cancel</Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- status
function StatusCard({ connection: c, problems, counts, onEdit, onChange }: {
  connection: Connection; problems: string[]; counts: Overview["counts"]; onEdit: () => void; onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const badge = connectionBadge(c);

  async function run(path: string, method = "POST", done?: string) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api(path, { method });
      if (done) setMsg(done);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold">Odoo</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>
            {c.server_version && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">
                {c.server_version} · {c.api === "json2" ? "JSON-2 API" : "JSON-RPC"}
              </span>
            )}
          </div>
          <p className="mt-1 break-all text-sm text-slate-500">{c.base_url}{c.database ? ` · ${c.database}` : ""}</p>
          <p className="mt-1 text-sm text-slate-500">
            {c.connected_at ? <>Syncing since {when(c.connected_at)} · prices and stock fetched {when(c.last_pull_at)}</>
              : "Check the settings below, then switch syncing on."}
          </p>
          {c.last_error && <p className="mt-2 text-sm text-red-600">{c.last_error}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {c.status === "active" ? (
            <>
              <Button variant="outline" disabled={busy} onClick={() => run("/integrations/sync", "POST", "Fetching prices and stock now.")}>
                <RefreshCcw size={16} /> Sync now
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => run("/integrations/pause")}><Pause size={16} /> Pause</Button>
            </>
          ) : (
            <Button disabled={busy || problems.length > 0} onClick={() => run("/integrations/activate", "POST", "Syncing is on.")}>
              <Play size={16} /> Switch syncing on
            </Button>
          )}
          <Button variant="ghost" disabled={busy} onClick={onEdit}>Connection details</Button>
        </div>
      </div>

      {problems.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" />
            <ul className="space-y-0.5 text-sm text-amber-900">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <Stat label="Sent" value={counts.ok} />
        <Stat label="To check" value={counts.warning} tone={counts.warning ? "warn" : undefined} />
        <Stat label="Failed" value={counts.failed} tone={counts.failed ? "bad" : undefined} />
      </div>

      {msg && <p className="mt-3 text-sm text-emerald-700">{msg}</p>}
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-4 border-t border-[var(--border)] pt-3">
        {confirmDisconnect ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <span className="text-sm text-slate-600">Disconnect Odoo? Nothing is deleted in Odoo; syncing stops.</span>
            <Button variant="danger" disabled={busy} onClick={() => run("/integrations", "DELETE")}>Disconnect</Button>
            <Button variant="outline" onClick={() => setConfirmDisconnect(false)}>Keep it</Button>
          </div>
        ) : (
          <Button variant="ghost" className="px-2 text-xs text-slate-500" onClick={() => setConfirmDisconnect(true)}>
            <Unplug size={14} /> Disconnect
          </Button>
        )}
      </div>
    </Card>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "warn" | "bad" }) {
  const color = tone === "bad" ? "text-red-600" : tone === "warn" ? "text-amber-700" : "";
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------- mapping
function Mapping({ connection, onSaved }: { connection: Connection; onSaved: () => void }) {
  const { branches } = useBranches();
  const [options, setOptions] = useState<Options | null>(null);
  const [s, setS] = useState<ConnectionSettings>(connection.settings);
  const [vat, setVat] = useState<string>("15.00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api("/integrations/options").then((r: ConnectResult) => setOptions(r.options)).catch((e) => setError(e.message));
    api("/accounts/settings").then((a) => setVat(Number(a.vat_rate).toFixed(2))).catch(() => {});
  }, []);
  useEffect(() => setS(connection.settings), [connection.settings]);

  async function save() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api("/integrations/settings", { method: "PUT", body: JSON.stringify(s) });
      setMsg("Settings saved.");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (!options) {
    return (
      <Card className="p-5">
        <h2 className="mb-2 text-sm font-semibold text-slate-500">SETTINGS</h2>
        {error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-sm text-slate-400">Reading your Odoo setup…</p>}
      </Card>
    );
  }

  const co = s.company_id ?? null;
  const ofCompany = <T extends { company_id?: number | null }>(rows: T[]) => rows.filter((r) => !r.company_id || r.company_id === co);
  const journals = ofCompany(options.journals);
  const rates = Array.from(new Set([vat, ...Object.keys(s.taxes ?? {})])).sort((a, b) => Number(b) - Number(a));
  const toggle = (key: keyof ConnectionSettings, label: string, hint: string) => (
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1" checked={!!s[key]} onChange={(e) => setS({ ...s, [key]: e.target.checked })} />
      <span><span className="font-medium">{label}</span><span className="block text-xs text-slate-500">{hint}</span></span>
    </label>
  );
  const num = (v: string) => (v ? Number(v) : null);

  return (
    <Card className="p-5">
      <h2 className="mb-4 text-sm font-semibold text-slate-500">SETTINGS</h2>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-slate-500">Odoo company
          <select className={`${select} mt-1`} value={co ?? ""} onChange={(e) => setS({ ...s, company_id: num(e.target.value) })}>
            {options.companies.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.currency})</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-500">Sales journal for invoices
          <select className={`${select} mt-1`} value={s.sales_journal_id ?? ""} onChange={(e) => setS({ ...s, sales_journal_id: num(e.target.value) })}>
            <option value="">Choose…</option>
            {journals.filter((j) => j.type === "sale").map((j) => <option key={j.id} value={j.id}>{j.name} ({j.code})</option>)}
          </select>
        </label>
        {rates.map((rate) => (
          <label key={rate} className="text-xs font-medium text-slate-500">Odoo tax for VAT {Number(rate)}%
            <select className={`${select} mt-1`} value={s.taxes?.[rate] ?? ""}
              onChange={(e) => setS({ ...s, taxes: { ...(s.taxes ?? {}), [rate]: Number(e.target.value) } })}>
              <option value="">Choose…</option>
              {ofCompany(options.taxes).filter((t) => t.amount.toFixed(2) === rate).map((t) => (
                <option key={t.id} value={t.id}>{t.name}{t.price_include ? " (included in price)" : ""}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Salesman already signs and reports invoices to ZATCA. Choose an Odoo sales journal that isn&apos;t connected to ZATCA,
        so nothing is reported twice.
      </p>

      <h3 className="mb-2 mt-6 text-sm font-semibold">Payments go to</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {Object.entries(METHOD_LABEL).map(([m, label]) => (
          <label key={m} className="text-xs font-medium text-slate-500">{label}
            <select className={`${select} mt-1`} value={s.payment_journals?.[m] ?? ""}
              onChange={(e) => setS({ ...s, payment_journals: { ...(s.payment_journals ?? {}), [m]: Number(e.target.value) } })}>
              <option value="">Choose…</option>
              {journals.filter((j) => j.type !== "sale").map((j) => <option key={j.id} value={j.id}>{j.name}</option>)}
            </select>
          </label>
        ))}
      </div>

      <h3 className="mb-2 mt-6 text-sm font-semibold">Branches</h3>
      <TableScroll>
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr><th className="py-2 pr-3 font-medium">Branch</th><th className="py-2 pr-3 font-medium">Odoo warehouse (stock)</th>
              <th className="py-2 font-medium">Odoo price list (optional)</th></tr>
          </thead>
          <tbody>
            {branches.filter((b) => b.is_active).map((b) => {
              const m = s.branches?.[b.id] ?? { warehouse_id: null, pricelist_id: null };
              const set = (patch: Partial<typeof m>) => setS({ ...s, branches: { ...(s.branches ?? {}), [b.id]: { ...m, ...patch } } });
              return (
                <tr key={b.id} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-3 font-medium">{b.name}</td>
                  <td className="py-2 pr-3">
                    <select className={select} value={m.warehouse_id ?? ""} onChange={(e) => set({ warehouse_id: num(e.target.value) })}>
                      <option value="">Choose…</option>
                      {ofCompany(options.warehouses).map((w) => <option key={w.id} value={w.id}>{w.name} ({w.code})</option>)}
                    </select>
                  </td>
                  <td className="py-2">
                    <select className={select} value={m.pricelist_id ?? ""} onChange={(e) => set({ pricelist_id: num(e.target.value) })}>
                      <option value="">Sales price on the product</option>
                      {ofCompany(options.pricelists).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.currency})</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>

      <h3 className="mb-2 mt-6 text-sm font-semibold">What to sync</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {toggle("pull_catalog", "Fetch products, prices and stock", "Matched on Odoo's Internal Reference = Salesman SKU")}
        {toggle("push_orders", "Send confirmed orders as sales orders", "Reserves the stock in Odoo right away")}
        {toggle("validate_deliveries", "Validate the delivery when an order is delivered", "Takes the stock out in Odoo")}
        {toggle("push_invoices", "Send invoices and credit notes", "Posted, and linked to the sales order")}
        {toggle("push_payments", "Send payments and reversals", "Matched to the invoices they paid")}
        <label className="text-sm">
          <span className="font-medium">Fetch every</span>
          <select className={`${select} mt-1`} value={s.pull_interval_minutes ?? 15}
            onChange={(e) => setS({ ...s, pull_interval_minutes: Number(e.target.value) })}>
            {[5, 10, 15, 30, 60, 240].map((n) => <option key={n} value={n}>{n < 60 ? `${n} minutes` : `${n / 60} hour${n > 60 ? "s" : ""}`}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mt-4 text-sm text-emerald-700">{msg}</p>}
      <Button className="mt-4" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save settings"}</Button>
    </Card>
  );
}

// ---------------------------------------------------------------- activity
function Activity({ version, active, onChange }: { version: number; active: boolean; onChange: () => void }) {
  const [filter, setFilter] = useState<"attention" | "">("");
  const [rows, setRows] = useState<SyncEvent[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRows(null);
    api(`/integrations/events${filter ? `?status=${filter}` : ""}`).then(setRows).catch((e) => setError(e.message));
  }, [filter, version]);

  async function retry(ev: SyncEvent) {
    setBusy(ev.id);
    setError("");
    try {
      await api(`/integrations/events/${ev.id}/retry`, { method: "POST" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold text-slate-500">ACTIVITY</h2>
        <div className="flex gap-2">
          {([["", "All"], ["attention", "Needs attention"]] as ["" | "attention", string][]).map(([k, label]) => (
            <button key={k || "all"} onClick={() => setFilter(k)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${filter === k ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "border-[var(--border)] bg-white text-slate-600"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">When</th>
                <th className="px-4 py-3 font-medium">What</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">In Odoo</th>
                <th className="px-4 py-3 font-medium">Details</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((ev) => {
                const b = statusBadge(ev.status);
                return (
                  <tr key={ev.id} className="border-b border-[var(--border)] last:border-0 align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{when(ev.updated_at)}</td>
                    <td className="px-4 py-3">
                      <div className="whitespace-nowrap font-medium">{ACTION_LABEL[ev.action] ?? ev.action}</div>
                      <div className="whitespace-nowrap font-mono text-xs text-slate-500">{ev.label}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs ${b.className}`}>{b.label}</span>
                      {ev.attempts > 1 && <div className="mt-0.5 text-xs text-slate-400">{ev.attempts} tries</div>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">{ev.external_ref ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-600">{ev.message ?? ""}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {active && (ev.status === "failed" || ev.status === "warning") && (
                        <Button variant="outline" className="px-2 py-1 text-xs" disabled={busy === ev.id} onClick={() => retry(ev)}>
                          <RefreshCcw size={14} /> Send again
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {rows === null && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
              {rows?.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                  {filter ? "Nothing needs attention." : "Nothing synced yet."}
                </td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </section>
  );
}

// ---------------------------------------------------------------- balances
function Balances() {
  const [rows, setRows] = useState<Balance[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function check() {
    setBusy(true);
    setError("");
    try { setRows(await api("/integrations/balances")); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  const off = (rows ?? []).filter((r) => Number(r.difference) !== 0);

  return (
    <Card className="p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-500">BALANCE CHECK</h2>
          <p className="mt-1 text-sm text-slate-500">
            Compares what each customer owes in Salesman with their balance in Odoo. Opening balances and Odoo entries made
            before connecting can explain a difference.
          </p>
        </div>
        <Button variant="outline" className="shrink-0 whitespace-nowrap" disabled={busy} onClick={check}>
          <Scale size={16} /> {busy ? "Comparing…" : "Compare balances"}
        </Button>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {rows && (
        <>
          <p className={`mt-3 text-sm ${off.length ? "text-amber-800" : "text-emerald-700"}`}>
            {rows.length === 0 ? "No customers have been sent to Odoo yet."
              : off.length ? `${off.length} of ${rows.length} customers don't match.` : `All ${rows.length} customers match.`}
          </p>
          {rows.length > 0 && (
            <TableScroll>
              <table className="mt-3 w-full min-w-[520px] text-sm">
                <thead className="text-left text-xs text-slate-500">
                  <tr><th className="py-2 pr-3 font-medium">Customer</th><th className="py-2 pr-3 text-right font-medium">Salesman</th>
                    <th className="py-2 pr-3 text-right font-medium">Odoo</th><th className="py-2 text-right font-medium">Difference</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.customer_id} className="border-t border-[var(--border)]">
                      <td className="py-2 pr-3">{r.name}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{Number(r.salesman).toFixed(2)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{Number(r.odoo).toFixed(2)}</td>
                      <td className={`py-2 text-right tabular-nums ${Number(r.difference) ? "font-medium text-red-600" : "text-slate-400"}`}>
                        {Number(r.difference).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}
        </>
      )}
    </Card>
  );
}