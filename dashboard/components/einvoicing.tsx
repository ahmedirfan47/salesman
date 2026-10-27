"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, downloadFile } from "@/lib/api";
import { useBranches, type Branch } from "@/lib/branches";
import { day, money } from "@/lib/accounts";
import {
  ENV_LABEL, FLOW_LABEL, TYPES_LABEL, edocBadge, unitBadge,
  type EDocument, type ZatcaOverview, type ZatcaUnit,
} from "@/lib/zatca";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, FileCode2, Plug, RefreshCw, Send, ShieldCheck } from "lucide-react";

type Filter = "attention" | "waiting" | "done" | "";

const select = "w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";

/** Accounts > E-invoicing: connect branches to ZATCA and follow every e-invoice. */
export function EInvoicing({ manage, onOpenSettings }: { manage: boolean; onOpenSettings: () => void }) {
  const { branches } = useBranches();
  const [overview, setOverview] = useState<ZatcaOverview | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  const load = useCallback(() => {
    api("/zatca").then(setOverview).catch((e) => setError(e.message));
    setVersion((v) => v + 1);
  }, []);
  useEffect(load, [load]);

  if (!overview) return error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-slate-400">Loading…</p>;
  const c = overview.counts;
  const active = branches.filter((b) => b.is_active);

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-600">{error}</p>}

      {overview.seller_problems.length > 0 && (
        <Card className="border-amber-200 bg-amber-50/60 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 shrink-0 text-amber-600" size={18} />
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold text-amber-900">Complete your business details first</h2>
              <p className="mt-1 text-sm text-amber-900/80">ZATCA checks these on every e-invoice:</p>
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-amber-900">
                {overview.seller_problems.map((p) => <li key={p}>{p}</li>)}
              </ul>
              {manage && <Button variant="outline" className="mt-3" onClick={onOpenSettings}>Open settings</Button>}
            </div>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Cleared (B2B)" value={c.cleared} hint="Approved by ZATCA before sharing" />
        <Stat label="Reported (B2C)" value={c.reported} hint="Sent within 24 hours" />
        <Stat label="Sending" value={c.waiting} hint="Retried automatically" />
        <Stat label="Need attention" value={c.rejected + c.blocked} hint="Fix and send again" tone={c.rejected + c.blocked > 0 ? "bad" : undefined} />
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-slate-500">BRANCHES</h2>
        <div className="space-y-3">
          {active.map((b) => (
            <BranchUnit key={b.id} branch={b} unit={overview.units.find((u) => u.branch_id === b.id)}
              manage={manage} blocked={overview.seller_problems.length > 0} onChange={load} />
          ))}
          {active.length === 0 && <Card className="p-6 text-sm text-slate-400">No branches.</Card>}
        </div>
      </section>

      <Documents manage={manage} version={version} onChange={load} />
    </div>
  );
}

// ---------------------------------------------------------------- connecting a branch
function BranchUnit({ branch, unit, manage, blocked, onChange }: {
  branch: Branch; unit: ZatcaUnit | undefined; manage: boolean; blocked: boolean; onChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [otp, setOtp] = useState("");
  const [f, setF] = useState({
    environment: unit?.environment ?? "production",
    location: unit?.location ?? [branch.address, branch.city].filter(Boolean).join(", "),
    industry: unit?.industry ?? "Wholesale of fruit and vegetables",
    invoice_types: unit?.invoice_types ?? "1100",
  });
  const badge = unitBadge(unit);
  const connected = unit?.status === "active";
  const midway = unit && unit.status !== "active" && unit.status !== "disabled";

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      onChange();
    } finally {
      setBusy(false);
    }
  }

  const prepare = () => run(async () => {
    await api("/zatca/units", { method: "POST", body: JSON.stringify({ branch_id: branch.id, ...f }) });
    setOpen(true);
  });
  const onboard = () => run(async () => {
    await api(`/zatca/units/${unit!.id}/onboard`, { method: "POST", body: JSON.stringify({ otp: otp.trim() || null }) });
    setOtp("");
  });

  return (
    <Card className="p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{branch.name}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>
            {unit && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">{ENV_LABEL[unit.environment]}</span>}
          </div>
          {connected && unit && (
            <p className="mt-1 text-sm text-slate-500">
              {TYPES_LABEL[unit.invoice_types]} · {unit.icv} document{unit.icv === 1 ? "" : "s"} signed
              {unit.certificate_expires_at && <> · certificate valid until {day(unit.certificate_expires_at)}</>}
            </p>
          )}
          {!unit && <p className="mt-1 text-sm text-slate-500">Invoices from this branch are not sent to ZATCA yet.</p>}
          {unit?.status === "disabled" && <p className="mt-1 text-sm text-slate-500">Turned off: new invoices are not signed or sent.</p>}
          {unit?.last_error && unit.status !== "active" && <p className="mt-1 text-sm text-red-600">{unit.last_error}</p>}
        </div>
        {manage && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {connected && (
              <Button variant="outline" disabled={busy} onClick={() => run(() => api(`/zatca/units/${unit!.id}/disable`, { method: "POST" }))}>
                Turn off
              </Button>
            )}
            {unit?.status === "disabled" && (
              <Button variant="outline" disabled={busy} onClick={() => run(() => api(`/zatca/units/${unit.id}/enable`, { method: "POST" }))}>
                Turn on
              </Button>
            )}
            {!connected && unit?.status !== "disabled" && (
              <Button variant={midway ? "outline" : "primary"} disabled={blocked} onClick={() => setOpen(!open)}>
                <Plug size={16} /> {midway ? "Continue" : "Connect to ZATCA"}
              </Button>
            )}
          </div>
        )}
      </div>

      {open && manage && !connected && (
        <div className="mt-4 space-y-4 border-t border-[var(--border)] pt-4">
          {!unit?.has_compliance_certificate && (
            <div>
              <h3 className="mb-2 text-sm font-semibold">1. Register this branch as an e-invoicing device</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="text-xs font-medium text-slate-500">Environment
                  <select className={`${select} mt-1`} value={f.environment}
                    onChange={(e) => setF({ ...f, environment: e.target.value as ZatcaUnit["environment"] })}>
                    <option value="production">Production (live invoices)</option>
                    <option value="simulation">Simulation (ZATCA test portal)</option>
                    <option value="sandbox">Developer sandbox (no portal account)</option>
                  </select>
                </label>
                <label className="text-xs font-medium text-slate-500">Invoices this branch issues
                  <select className={`${select} mt-1`} value={f.invoice_types}
                    onChange={(e) => setF({ ...f, invoice_types: e.target.value as ZatcaUnit["invoice_types"] })}>
                    {Object.entries(TYPES_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label className="text-xs font-medium text-slate-500">Branch address
                  <Input className="mt-1" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} />
                </label>
                <label className="text-xs font-medium text-slate-500">Industry
                  <Input className="mt-1" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} />
                </label>
              </div>
              <Button className="mt-3" variant={unit ? "outline" : "primary"} disabled={busy || !f.location.trim() || !f.industry.trim()} onClick={prepare}>
                {busy ? "Preparing…" : unit ? "Start again with these details" : "Create the device key"}
              </Button>
            </div>
          )}

          {unit && (
            <div>
              <h3 className="mb-1 text-sm font-semibold">{unit.has_compliance_certificate ? "Finish the compliance checks" : "2. Enter the OTP from the Fatoora portal"}</h3>
              {!unit.has_compliance_certificate && (
                <p className="mb-2 text-sm text-slate-500">
                  {unit.environment === "sandbox"
                    ? "The developer sandbox accepts any 6-digit code, e.g. 123345."
                    : <>Sign in to the {unit.environment === "simulation" ? "simulation" : "Fatoora"} portal, choose <em>Onboard new solution unit/device</em>, and generate an OTP. It is valid for one hour.</>}
                </p>
              )}
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                {!unit.has_compliance_certificate && (
                  <Input className="sm:w-40" inputMode="numeric" placeholder="OTP" value={otp} onChange={(e) => setOtp(e.target.value)} />
                )}
                <Button disabled={busy || (!unit.has_compliance_certificate && !otp.trim())} onClick={onboard}>
                  <ShieldCheck size={16} /> {busy ? "Talking to ZATCA…" : unit.has_compliance_certificate ? "Run the checks again" : "Connect"}
                </Button>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                We then sign one test document of each type and ask ZATCA to check it, and receive the production certificate.
              </p>
            </div>
          )}

          {unit && unit.compliance_results.length > 0 && (
            <ul className="space-y-1 text-sm">
              {unit.compliance_results.map((r) => (
                <li key={r.label} className="flex items-start gap-2">
                  {r.status === "ERROR"
                    ? <AlertTriangle size={15} className="mt-0.5 shrink-0 text-red-600" />
                    : <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-600" />}
                  <span>
                    {r.label}
                    {r.errors.length > 0 && <span className="text-red-600"> — {r.errors.map((e) => e.message || e.code).join("; ")}</span>}
                    {r.errors.length === 0 && r.warnings.length > 0 && <span className="text-amber-700"> — {r.warnings.length} warning{r.warnings.length === 1 ? "" : "s"}</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}
      {!open && error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- e-invoices
function Documents({ manage, version, onChange }: { manage: boolean; version: number; onChange: () => void }) {
  const { branches, nameOf } = useBranches();
  const [filter, setFilter] = useState<Filter>("attention");
  const [rows, setRows] = useState<EDocument[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setRows(null);
    api(`/zatca/documents${filter ? `?status=${filter}` : ""}`).then(setRows).catch((e) => setError(e.message));
  }, [filter, version]);

  async function act(doc: EDocument, action: "send" | "resubmit") {
    setBusy(doc.id);
    setError("");
    setMsg("");
    try {
      const next: EDocument = await api(`/zatca/documents/${doc.id}/${action}`, { method: "POST" });
      setMsg(
        action === "send" ? `${doc.invoice_number} will be sent again in a moment.`
          : next.status === "blocked" ? `${doc.invoice_number} still has missing details: ${next.errors.map((e) => e.message).join(" ")}`
            : `${doc.invoice_number} was corrected and signed again (document ${next.icv}). It is being sent now.`,
      );
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  async function xml(doc: EDocument) {
    try { await downloadFile(`/zatca/documents/${doc.id}/xml`, `${doc.invoice_number}.xml`); }
    catch (e) { setError(e instanceof Error ? e.message : "Download failed"); }
  }

  return (
    <section>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold text-slate-500">E-INVOICES</h2>
        <div className="flex flex-wrap gap-2">
          {([["attention", "Need attention"], ["waiting", "Sending"], ["done", "Cleared and reported"], ["", "All"]] as [Filter, string][]).map(([k, label]) => (
            <button key={k || "all"} onClick={() => setFilter(k)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${filter === k ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "border-[var(--border)] bg-white text-slate-600"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-3 text-sm text-emerald-700">{msg}</p>}
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="w-8 px-2 py-3"></th>
                <th className="px-4 py-3 font-medium">Document</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Issued</th>
                <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">ZATCA</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((d) => {
                const b = edocBadge(d.status, d.flow);
                const expanded = openId === d.id;
                const notes = d.errors.length + d.warnings.length + (d.last_error ? 1 : 0);
                return (
                  <FragmentRows key={d.id}>
                    <tr className="border-b border-[var(--border)]">
                      <td className="px-2 py-3 text-slate-400">
                        {notes > 0 && (
                          <button onClick={() => setOpenId(expanded ? null : d.id)} aria-label="Details">
                            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="whitespace-nowrap font-mono text-xs">{d.invoice_number}</span>
                        <div className="text-xs text-slate-400">{d.kind === "credit_note" ? "Credit note" : "Invoice"}{d.icv ? ` · #${d.icv}` : ""}{branches.length > 1 ? ` · ${nameOf(d.branch_id)}` : ""}</div>
                      </td>
                      <td className="px-4 py-3">
                        {d.customer_id
                          ? <Link className="text-[var(--primary)] hover:underline" href={`/accounts/${d.customer_id}`}>{d.buyer_name}</Link>
                          : d.buyer_name || "Walk-in"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{day(d.issue_date)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{money(d.currency, d.total)}</td>
                      <td className="px-4 py-3 text-slate-600">{FLOW_LABEL[d.flow]}</td>
                      <td className="px-4 py-3">
                        <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs ${b.className}`}>{b.label}</span>
                        {d.status === "queued" && d.attempts > 0 && <div className="mt-0.5 text-xs text-slate-400">attempt {d.attempts}</div>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex justify-end gap-2">
                          {manage && (d.status === "rejected" || d.status === "blocked") && (
                            <Button className="px-2 py-1 text-xs" disabled={busy === d.id} onClick={() => act(d, "resubmit")}>
                              <RefreshCw size={14} /> Fix and resend
                            </Button>
                          )}
                          {manage && d.status === "queued" && (
                            <Button variant="outline" className="px-2 py-1 text-xs" disabled={busy === d.id} onClick={() => act(d, "send")}>
                              <Send size={14} /> Send now
                            </Button>
                          )}
                          {d.status !== "blocked" && (
                            <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => xml(d)}><FileCode2 size={14} /> XML</Button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="border-b border-[var(--border)] bg-gray-50/70">
                        <td></td>
                        <td colSpan={7} className="px-4 py-3 text-sm">
                          {d.last_error && <p className="text-slate-600">{d.last_error}</p>}
                          {d.errors.map((e, i) => (
                            <p key={`e${i}`} className="text-red-700">{e.code ? <span className="font-mono text-xs">{e.code} </span> : null}{e.message}</p>
                          ))}
                          {d.warnings.map((w, i) => (
                            <p key={`w${i}`} className="text-amber-800">{w.code ? <span className="font-mono text-xs">{w.code} </span> : null}{w.message}</p>
                          ))}
                          {(d.status === "rejected" || d.status === "blocked") && (
                            <p className="mt-2 text-xs text-slate-500">
                              Correct the customer&apos;s details on their account page (or the business details in Settings), then press <em>Fix and resend</em>.
                              A corrected e-invoice is signed again with a new counter; the invoice number stays the same.
                            </p>
                          )}
                        </td>
                      </tr>
                    )}
                  </FragmentRows>
                );
              })}
              {rows === null && <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
              {rows?.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">
                  {filter === "attention" ? "Nothing needs attention." : filter === "waiting" ? "Nothing waiting to be sent." : "No e-invoices yet."}
                </td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </section>
  );
}

function FragmentRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function Stat({ label, value, hint, tone }: { label: string; value: number; hint?: string; tone?: "bad" }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-lg font-bold tabular-nums ${tone === "bad" ? "text-red-600" : ""}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </Card>
  );
}