"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ACTION_LABEL, CLIENT_LABEL, SIGN_IN_REASON, when, type AuditEntry, type SignIn } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { TableScroll } from "@/components/table-scroll";

type Tab = "actions" | "sign-ins" | "failed";

function describe(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([key, value]) => {
      if (value && typeof value === "object" && "from" in value && "to" in value) {
        const v = value as { from: unknown; to: unknown };
        return `${key.replaceAll("_", " ")}: ${String(v.from) || "empty"} → ${String(v.to) || "empty"}`;
      }
      return `${key.replaceAll("_", " ")}: ${String(value)}`;
    })
    .join("; ");
}

export default function ActivityPage() {
  const [tab, setTab] = useState<Tab>("actions");
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [signIns, setSignIns] = useState<SignIn[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    if (tab === "actions") {
      setAudit(null);
      api("/platform/audit").then(setAudit).catch((e) => setError(e.message));
    } else {
      setSignIns(null);
      api(`/platform/sign-ins${tab === "failed" ? "?failed=true" : ""}`).then(setSignIns).catch((e) => setError(e.message));
    }
  }, [tab]);

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {([["actions", "Console actions"], ["sign-ins", "All sign-ins"], ["failed", "Failed sign-ins"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${tab === k ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "border-[var(--border)] bg-white text-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {tab === "actions" ? (
        <Card className="overflow-hidden">
          <TableScroll>
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3 font-medium">Who</th>
                  <th className="px-4 py-3 font-medium">What</th><th className="px-4 py-3 font-medium">Details</th>
                </tr>
              </thead>
              <tbody>
                {(audit ?? []).map((a) => (
                  <tr key={a.id} className="border-b border-[var(--border)] align-top last:border-0">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{when(a.created_at)}</td>
                    <td className="px-4 py-3">{a.actor_email}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{ACTION_LABEL[a.action] ?? a.action}</div>
                      {a.target_label && <div className="text-xs text-slate-500">{a.target_label}</div>}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{describe(a.detail)}</td>
                  </tr>
                ))}
                {audit === null && !error && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
                {audit?.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Nothing changed from the console yet</td></tr>}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <TableScroll>
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Business</th><th className="px-4 py-3 font-medium">From</th>
                  <th className="px-4 py-3 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {(signIns ?? []).map((s) => (
                  <tr key={s.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{when(s.at)}</td>
                    <td className="px-4 py-3">{s.email}</td>
                    <td className="px-4 py-3 text-slate-600">{s.business ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-600">{CLIENT_LABEL[s.client] ?? s.client}{s.ip && <span className="block text-xs text-slate-400">{s.ip}</span>}</td>
                    <td className={`px-4 py-3 ${s.success ? "text-emerald-700" : "text-red-600"}`}>{SIGN_IN_REASON[s.reason] ?? s.reason}</td>
                  </tr>
                ))}
                {signIns === null && !error && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
                {signIns?.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No sign-ins yet</td></tr>}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}
    </div>
  );
}