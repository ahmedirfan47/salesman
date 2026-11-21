"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { useBranches } from "@/lib/branches";
import {
  ACTION_LABEL, METHOD_LABEL, PROVIDER_HELP, PROVIDER_NAME, connectionBadge, statusBadge, when,
  type Balance, type Connection, type ConnectionSettings, type ConnectResult, type DryRun, type Health,
  type Options, type Overview, type Provider, type SyncEvent, type TestResult,
} from "@/lib/integrations";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import {
  Activity as ActivityIcon, AlertTriangle, Cable, CheckCircle2, Eye, Pause, Play, PlugZap, RefreshCcw, Scale,
  ShieldAlert, Unplug, XCircle,
} from "lucide-react";

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
  const name = conn ? PROVIDER_NAME[conn.provider] ?? conn.provider : "";

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
          <StatusCard connection={conn} name={name} problems={overview.problems} counts={overview.counts}
            onEdit={() => setEditing(true)} onChange={load} />
          <HealthCard version={version} name={name} />
          <Mapping connection={conn} name={name} onSaved={load} />
          <DryRunCard name={name} />
          <Activity version={version} name={name} active={conn.status === "active"} onChange={load} />
          <Balances name={name} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- connecting
const FIELD_ORDER = ["tenant", "url", "database", "username", "api_key"];

function ConnectCard({ providers, connection, onDone, onCancel }: {
  providers: Provider[]; connection: Connection | null; onDone: () => void; onCancel?: () => void;
}) {
  const [provider, setProvider] = useState(connection?.provider ?? "");
  const [f, setF] = useState<Record<string, string>>({
    url: connection?.base_url ?? "", database: connection?.database ?? "", username: connection?.username ?? "",
    api_key: "", tenant: connection?.settings.aad_tenant ?? "",
  });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const chosen = providers.find((p) => p.key === provider);
  const name = PROVIDER_NAME[provider] ?? chosen?.name ?? provider;

  async function connect() {
    setBusy(true);
    setError("");
    try {
      const fields = chosen?.connect_fields ?? {};
      const body: Record<string, string | null> = { provider };
      for (const k of FIELD_ORDER) {
        if (k in fields || k === "api_key") body[k] = (f[k] ?? "").trim() || (fields[k]?.default ?? null);
      }
      await api("/integrations/connect", { method: "POST", body: JSON.stringify(body) }) as ConnectResult;
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

  const fields = chosen?.connect_fields ?? {};
  const keys = FIELD_ORDER.filter((k) => k in fields);
  const visible = keys.filter((k) => !fields[k].advanced || showAdvanced);
  const required = keys.filter((k) => !fields[k].optional && !fields[k].advanced && k !== "api_key");
  const ready = required.every((k) => (f[k] ?? "").trim()) && (connection || (f.api_key ?? "").trim());

  return (
    <Card className="p-5">
      <h2 className="mb-1 font-semibold">{connection ? "Connection details" : `Connect ${name}`}</h2>
      <p className="mb-4 text-sm text-slate-500">{PROVIDER_HELP[provider]}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {visible.map((k) => (
          <label key={k} className="text-xs font-medium text-slate-500">{fields[k].label}{fields[k].optional ? " (optional)" : ""}
            <Input className="mt-1" type={k === "api_key" ? "password" : "text"} autoComplete="off"
              placeholder={k === "api_key" && connection ? "Leave empty to keep the saved one" : fields[k].placeholder ?? ""}
              value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      {keys.some((k) => fields[k].advanced) && !showAdvanced && (
        <button type="button" className="mt-2 text-xs text-[var(--primary)]" onClick={() => setShowAdvanced(true)}>Advanced</button>
      )}
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button disabled={busy || !ready} onClick={connect}>
          <Cable size={16} /> {busy ? `Checking with ${name}…` : connection ? "Save and check" : "Connect"}
        </Button>
        <Button variant="outline" onClick={() => (onCancel ? onCancel() : setProvider(""))}>Cancel</Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- status
function StatusCard({ connection: c, name, problems, counts, onEdit, onChange }: {
  connection: Connection; name: string; problems: string[]; counts: Overview["counts"]; onEdit: () => void; onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [test, setTest] = useState<TestResult | null>(null);
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

  async function testConnection() {
    setBusy(true);
    setError("");
    setTest(null);
    try {
      setTest(await api("/integrations/test", { method: "POST" }));
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const apiLabel = c.api === "json2" ? "JSON-2 API" : c.api === "jsonrpc" ? "JSON-RPC" : c.api === "service_layer" ? "Service Layer" : c.api === "api_v2" ? "API v2.0" : c.api;

  return (
    <Card className="p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold">{name}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>
            {c.server_version && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">{c.server_version}{apiLabel ? ` · ${apiLabel}` : ""}</span>
            )}
          </div>
          <p className="mt-1 break-all text-sm text-slate-500">{c.base_url}{c.database ? ` · ${c.database}` : ""}</p>
          <p className="mt-1 text-sm text-slate-500">
            {c.connected_at ? <>Syncing since {when(c.connected_at)} · prices and stock fetched {when(c.last_pull_at)}</>
              : "Test the connection, preview the first sync, check the settings below, then switch syncing on."}
          </p>
          {c.last_error && <p className="mt-2 text-sm text-red-600">{c.last_error}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={testConnection}><PlugZap size={16} /> Test connection</Button>
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

      {test && (
        <div className={`mt-4 rounded-lg border p-3 text-sm ${test.ok ? "border-emerald-200 bg-emerald-50/60 text-emerald-900" : "border-red-200 bg-red-50/60 text-red-800"}`}>
          <div className="flex items-start gap-2">
            {test.ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <XCircle size={16} className="mt-0.5 shrink-0" />}
            <div>
              <div>{test.message}</div>
              {test.ok && (
                <div className="mt-1 text-xs opacity-80">
                  {test.companies} compan{test.companies === 1 ? "y" : "ies"} · {test.warehouses} warehouse(s) · {test.price_lists} price list(s) · {test.taxes} tax code(s)
                </div>
              )}
            </div>
          </div>
        </div>
      )}

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
            <span className="text-sm text-slate-600">Disconnect {name}? Nothing is deleted in {name}; syncing stops.</span>
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

// ---------------------------------------------------------------- health
const HEALTH_BADGE: Record<Health["status"], string> = {
  healthy: "bg-emerald-50 text-emerald-700", degraded: "bg-amber-50 text-amber-800", down: "bg-red-50 text-red-700",
  off: "bg-gray-100 text-slate-600",
};
const HEALTH_LABEL: Record<Health["status"], string> = { healthy: "Healthy", degraded: "Needs a look", down: "Not working", off: "Switched off" };

function HealthCard({ version, name }: { version: number; name: string }) {
  const [h, setH] = useState<Health | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/integrations/health").then(setH).catch((e) => setError(e.message)); }, [version]);

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center gap-2">
        <ActivityIcon size={16} className="text-slate-400" />
        <h2 className="text-sm font-semibold text-slate-500">HEALTH</h2>
        {h && <span className={`rounded-full px-2 py-0.5 text-xs ${HEALTH_BADGE[h.status]}`}>{HEALTH_LABEL[h.status]}</span>}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!h && !error && <p className="text-sm text-slate-400">Checking {name}…</p>}
      {h && (
        <ul className="space-y-1.5 text-sm">
          {h.checks.map((c) => (
            <li key={c.key} className="flex items-start gap-2">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${c.status === "ok" ? "bg-emerald-500" : c.status === "error" ? "bg-red-500" : c.status === "warning" ? "bg-amber-500" : "bg-slate-300"}`} />
              <span className={c.status === "error" ? "text-red-700" : "text-slate-600"}>{c.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- mapping
function Mapping({ connection, name, onSaved }: { connection: Connection; name: string; onSaved: () => void }) {
  const { branches } = useBranches();
  const [options, setOptions] = useState<Options | null>(null);
  const [s, setS] = useState<ConnectionSettings>(connection.settings);
  const [vat, setVat] = useState<string>("15.00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const provider = connection.provider;

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
        {error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-sm text-slate-400">Reading your {name} setup…</p>}
      </Card>
    );
  }

  const L = options.labels ?? {};
  const co = s.company_id ?? null;
  const same = (a: unknown, b: unknown) => String(a) === String(b);
  const ofCompany = <T extends { company_id?: unknown }>(rows: T[]) => rows.filter((r) => !r.company_id || same(r.company_id, co));
  const journals = ofCompany(options.journals);
  const rates = Array.from(new Set([vat, ...Object.keys(s.taxes ?? {})])).sort((a, b) => Number(b) - Number(a));
  const toggle = (key: keyof ConnectionSettings, label: string, hint: string) => (
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1" checked={!!s[key]} onChange={(e) => setS({ ...s, [key]: e.target.checked })} />
      <span><span className="font-medium">{label}</span><span className="block text-xs text-slate-500">{hint}</span></span>
    </label>
  );
  const val = (v: string) => (v ? v : null);
  const taxChoices = (rate: string) => {
    const known = ofCompany(options.taxes).filter((t) => t.amount !== null && t.amount.toFixed(2) === rate);
    return provider === "dynamics_bc" || known.length === 0 ? ofCompany(options.taxes) : known;
  };
  const hasPricelists = options.pricelists.length > 0;

  return (
    <Card className="p-5">
      <h2 className="mb-4 text-sm font-semibold text-slate-500">SETTINGS</h2>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-slate-500">{name} company
          <select className={`${select} mt-1`} value={co ?? ""} disabled={options.companies.length < 2}
            onChange={(e) => setS({ ...s, company_id: val(e.target.value) })}>
            {options.companies.map((c) => <option key={String(c.id)} value={String(c.id)}>{c.name}{c.currency ? ` (${c.currency})` : ""}</option>)}
          </select>
        </label>
        {provider === "odoo" && (
          <label className="text-xs font-medium text-slate-500">Sales journal for invoices
            <select className={`${select} mt-1`} value={s.sales_journal_id ?? ""} onChange={(e) => setS({ ...s, sales_journal_id: val(e.target.value) })}>
              <option value="">Choose…</option>
              {journals.filter((j) => j.type === "sale").map((j) => <option key={String(j.id)} value={String(j.id)}>{j.name} ({j.code})</option>)}
            </select>
          </label>
        )}
        {provider === "sap_b1" && (
          <label className="text-xs font-medium text-slate-500">{L.sales_journal_id ?? "Default price list"}
            <select className={`${select} mt-1`} value={s.sales_journal_id ?? ""} onChange={(e) => setS({ ...s, sales_journal_id: val(e.target.value) })}>
              <option value="">Choose…</option>
              {options.pricelists.map((p) => <option key={String(p.id)} value={String(p.id)}>{p.name} ({p.currency})</option>)}
            </select>
          </label>
        )}
        {rates.map((rate) => (
          <label key={rate} className="text-xs font-medium text-slate-500">
            {provider === "dynamics_bc" ? `Tax group for VAT ${Number(rate)}% (optional)` : `${name} tax for VAT ${Number(rate)}%`}
            <select className={`${select} mt-1`} value={s.taxes?.[rate] ?? ""}
              onChange={(e) => {
                const taxes = { ...(s.taxes ?? {}) };
                if (e.target.value) taxes[rate] = e.target.value; else delete taxes[rate];
                setS({ ...s, taxes });
              }}>
              <option value="">{provider === "dynamics_bc" ? "Use the item's own setup" : "Choose…"}</option>
              {taxChoices(rate).map((t) => (
                <option key={String(t.id)} value={String(t.id)}>{t.name}{t.price_include ? " (included in price)" : ""}</option>
              ))}
            </select>
          </label>
        ))}
        {(options.accounts?.length ?? 0) > 0 && (
          <label className="text-xs font-medium text-slate-500">{L.adjustment_account ?? "Account for lines without an item"}
            <select className={`${select} mt-1`} value={s.adjustment_account ?? ""} onChange={(e) => setS({ ...s, adjustment_account: val(e.target.value) })}>
              <option value="">Choose…</option>
              {options.accounts!.map((a) => <option key={String(a.id)} value={String(a.id)}>{a.name}</option>)}
            </select>
          </label>
        )}
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Salesman already signs and reports invoices to ZATCA. Switch off ZATCA reporting in {name} for documents Salesman
        sends, so nothing is reported twice.
      </p>

      <h3 className="mb-2 mt-6 text-sm font-semibold">Payments go to</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {Object.entries(METHOD_LABEL).map(([m, label]) => (
          <label key={m} className="text-xs font-medium text-slate-500">{label}
            <select className={`${select} mt-1`} value={s.payment_journals?.[m] ?? ""}
              onChange={(e) => setS({ ...s, payment_journals: { ...(s.payment_journals ?? {}), [m]: e.target.value } })}>
              <option value="">Choose…</option>
              {journals.filter((j) => j.type !== "sale").map((j) => <option key={String(j.id)} value={String(j.id)}>{j.name}</option>)}
            </select>
          </label>
        ))}
      </div>

      <h3 className="mb-2 mt-6 text-sm font-semibold">Branches</h3>
      <TableScroll>
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="py-2 pr-3 font-medium">Branch</th>
              <th className="py-2 pr-3 font-medium">{L.warehouse ?? `${name} warehouse`} (stock)</th>
              {hasPricelists && <th className="py-2 font-medium">{L.pricelist ?? `${name} price list`} (optional)</th>}
            </tr>
          </thead>
          <tbody>
            {branches.filter((b) => b.is_active).map((b) => {
              const m = s.branches?.[b.id] ?? { warehouse_id: null, pricelist_id: null };
              const set = (patch: Partial<typeof m>) => setS({ ...s, branches: { ...(s.branches ?? {}), [b.id]: { ...m, ...patch } } });
              return (
                <tr key={b.id} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-3 font-medium">{b.name}</td>
                  <td className="py-2 pr-3">
                    <select className={select} value={m.warehouse_id ?? ""} onChange={(e) => set({ warehouse_id: val(e.target.value) })}>
                      <option value="">Choose…</option>
                      {ofCompany(options.warehouses).map((w) => <option key={String(w.id)} value={String(w.id)}>{w.name} ({w.code})</option>)}
                    </select>
                  </td>
                  {hasPricelists && (
                    <td className="py-2">
                      <select className={select} value={m.pricelist_id ?? ""} onChange={(e) => set({ pricelist_id: val(e.target.value) })}>
                        <option value="">{provider === "sap_b1" ? "Default price list" : "Sales price on the product"}</option>
                        {ofCompany(options.pricelists).map((p) => <option key={String(p.id)} value={String(p.id)}>{p.name} ({p.currency})</option>)}
                      </select>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>

      <h3 className="mb-2 mt-6 text-sm font-semibold">What to sync</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {toggle("pull_catalog", "Fetch products, prices and stock",
          provider === "odoo" ? "Matched on Odoo's Internal Reference = Salesman SKU" : provider === "sap_b1" ? "Matched on SAP Item Code = Salesman SKU" : "Matched on item No. = Salesman SKU")}
        {toggle("push_orders", "Send confirmed orders as sales orders", `Reserves the stock in ${name} right away`)}
        {provider !== "dynamics_bc" && toggle("validate_deliveries", "Record the delivery when an order is delivered", `Takes the stock out in ${name}`)}
        {toggle("push_invoices", "Send invoices and credit notes", "Linked to the sales order or the original invoice")}
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

// ---------------------------------------------------------------- dry run
function DryRunCard({ name }: { name: string }) {
  const [r, setR] = useState<DryRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function preview() {
    setBusy(true);
    setError("");
    try { setR(await api("/integrations/dry-run", { method: "POST" })); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-500">PREVIEW THE NEXT SYNC</h2>
          <p className="mt-1 text-sm text-slate-500">
            Reads {name} and shows what the next price and stock sync would change in each branch. Nothing is written.
          </p>
        </div>
        <Button variant="outline" className="shrink-0 whitespace-nowrap" disabled={busy} onClick={preview}>
          <Eye size={16} /> {busy ? `Reading ${name}…` : "Preview"}
        </Button>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {r && (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-slate-600">
            {r.products} product(s) in {name}{r.new_products ? `, ${r.new_products} not yet in Salesman` : ""}.
            {r.message && <span className="ml-1">{r.message}</span>}
          </p>
          {r.branches.map((b) => (
            <div key={b.branch} className="rounded-lg border border-[var(--border)] p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">{b.branch}</span>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">{b.products} products</span>
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">{b.new} new</span>
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-800">{b.price_changes} price change(s)</span>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">{b.stock_changes} stock change(s)</span>
              </div>
              {b.not_in_erp_count > 0 && (
                <p className="mt-2 text-xs text-red-700">
                  {b.not_in_erp_count} product(s) sold here today are not in {name} and would leave this branch&apos;s price list:{" "}
                  <span className="font-mono">{b.not_in_erp.slice(0, 12).join(", ")}{b.not_in_erp_count > 12 ? "…" : ""}</span>
                </p>
              )}
              {b.examples.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-slate-600">
                  {b.examples.slice(0, 8).map((e) => (
                    <li key={`${e.sku}-${e.kind}`}>
                      <span className="font-mono">{e.sku}</span>{" "}
                      {e.kind === "new" ? `new at ${Number(e.price).toFixed(2)}, ${e.quantity} in stock`
                        : e.kind === "price" ? `price ${Number(e.from).toFixed(2)} → ${Number(e.to).toFixed(2)}`
                        : `stock ${e.from} → ${e.to}`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {r.notes.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-800">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- activity
function Activity({ version, name, active, onChange }: { version: number; name: string; active: boolean; onChange: () => void }) {
  const [filter, setFilter] = useState<"attention" | "">("");
  const [rows, setRows] = useState<SyncEvent[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRows(null);
    api(`/integrations/events${filter ? `?status=${filter}` : ""}`).then(setRows).catch((e) => setError(e.message));
  }, [filter, version]);

  async function retry(path: string, key: string) {
    setBusy(key);
    setError("");
    try {
      await api(path, { method: "POST" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  const failed = (rows ?? []).filter((r) => r.status === "failed" && r.direction === "push").length;

  return (
    <section>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold text-slate-500">ACTIVITY</h2>
        <div className="flex flex-wrap gap-2">
          {active && failed > 0 && (
            <Button variant="outline" className="px-3 py-1 text-xs" disabled={busy === "all"}
              onClick={() => retry("/integrations/events/retry-failed", "all")}>
              <RefreshCcw size={14} /> Send all failed again
            </Button>
          )}
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
                <th className="whitespace-nowrap px-4 py-3 font-medium">In {name}</th>
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
                        <Button variant="outline" className="px-2 py-1 text-xs" disabled={busy === ev.id}
                          onClick={() => retry(`/integrations/events/${ev.id}/retry`, ev.id)}>
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
function Balances({ name }: { name: string }) {
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
            Compares what each customer owes in Salesman with their balance in {name}. Opening balances, entries made in {name}
            before connecting, and payments not yet posted can explain a difference.
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
            {rows.length === 0 ? `No customers have been sent to ${name} yet.`
              : off.length ? `${off.length} of ${rows.length} customers don't match.` : `All ${rows.length} customers match.`}
          </p>
          {rows.length > 0 && (
            <TableScroll>
              <table className="mt-3 w-full min-w-[520px] text-sm">
                <thead className="text-left text-xs text-slate-500">
                  <tr><th className="py-2 pr-3 font-medium">Customer</th><th className="py-2 pr-3 text-right font-medium">Salesman</th>
                    <th className="py-2 pr-3 text-right font-medium">{name}</th><th className="py-2 text-right font-medium">Difference</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.customer_id} className="border-t border-[var(--border)]">
                      <td className="py-2 pr-3">{r.name}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{Number(r.salesman).toFixed(2)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{Number(r.erp ?? r.odoo).toFixed(2)}</td>
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
