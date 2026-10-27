"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, downloadFile } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { SalesInvoiceDetail, invoiceBadge, money, day } from "@/lib/accounts";
import { FLOW_LABEL, edocBadge } from "@/lib/zatca";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Truck, PackageCheck, CheckCircle2, XCircle, Package, FileText, Download } from "lucide-react";
import { OrderProgress } from "@/components/order-progress";
import { TableScroll } from "@/components/table-scroll";
import { useBranches } from "@/lib/branches";

type Item = { id: string; sku: string; product_name: string; quantity: number; unit_price: string; line_total: string };
type Event = { from_status: string | null; to_status: string; actor_name: string | null; note: string | null; created_at: string };
type Order = {
  id: string; branch_id: string; order_number: string; status: string;
  customer_name: string | null; total_amount: string; currency: string;
  created_at: string; items: Item[]; events: Event[];
};

const statusColor: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-700",
  preparing: "bg-violet-50 text-violet-700",
  dispatched: "bg-blue-50 text-blue-700",
  delivered: "bg-indigo-50 text-indigo-700",
  completed: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-red-50 text-red-700",
  requires_human_review: "bg-amber-50 text-amber-700",
};

const nextActions: Record<string, { to: string; label: string; icon: typeof Truck; variant?: "primary" | "danger" }[]> = {
  confirmed: [
    { to: "preparing", label: "Start Preparing", icon: Package },
    { to: "dispatched", label: "Mark Dispatched", icon: Truck },
    { to: "cancelled", label: "Cancel", icon: XCircle, variant: "danger" },
  ],
  preparing: [
    { to: "dispatched", label: "Mark Dispatched", icon: Truck },
    { to: "cancelled", label: "Cancel", icon: XCircle, variant: "danger" },
  ],
  dispatched: [
    { to: "delivered", label: "Mark Delivered", icon: PackageCheck },
    { to: "cancelled", label: "Cancel", icon: XCircle, variant: "danger" },
  ],
  delivered: [
    { to: "completed", label: "Complete Order", icon: CheckCircle2 },
  ],
};

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { branches, nameOf } = useBranches();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);

  function load() {
    api(`/orders/${id}`)
      .then(setOrder)
      .catch((e) => setError(e.message));
    setVersion((v) => v + 1);
  }
  useEffect(load, [id]);

  async function transition(to: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/orders/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_status: to }),
      });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (!order) {
    return (
      <div>
        <Link href="/orders" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft size={16} /> Back</Link>
        {error ? <p className="text-red-600">{error}</p> : <p className="text-slate-400">Loading…</p>}
      </div>
    );
  }

  const actions = nextActions[order.status] ?? [];

  return (
    <div className="max-w-3xl">
      <Link href="/orders" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft size={16} /> Back to Orders
      </Link>

      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">{order.order_number}</h1>
          <p className="text-sm text-slate-500">
            {order.customer_name ?? "—"}
            {branches.length > 1 && nameOf(order.branch_id) && <> · {nameOf(order.branch_id)} branch</>}
          </p>
        </div>
        <span className={`w-fit rounded-full px-3 py-1 text-sm font-medium ${statusColor[order.status] ?? "bg-gray-100"}`}>
          {order.status.replace(/_/g, " ")}
        </span>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <Card className="mb-6 p-6">
        <OrderProgress status={order.status} />
      </Card>

      {/* action buttons */}
      {actions.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-3">
          {actions.map((a) => (
            <Button key={a.to} variant={a.variant ?? "primary"} disabled={busy} onClick={() => transition(a.to)} className="flex-1 sm:flex-none">
              <a.icon size={16} />
              {a.label}
            </Button>
          ))}
        </div>
      )}

      <InvoiceCard orderId={order.id} status={order.status} version={version} setError={setError} />

      {/* items */}
      <Card className="mb-6 overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[500px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Product</th>
                <th className="px-4 py-3 font-medium text-right">Qty</th>
                <th className="px-4 py-3 font-medium text-right">Unit</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((it) => (
                <tr key={it.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-3">{it.product_name} <span className="text-xs text-slate-400">({it.sku})</span></td>
                  <td className="px-4 py-3 text-right">{it.quantity}</td>
                  <td className="px-4 py-3 text-right">{Number(it.unit_price).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">{Number(it.line_total).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="font-semibold">
                <td className="px-4 py-3" colSpan={3}>Total</td>
                <td className="px-4 py-3 text-right">{order.currency} {Number(order.total_amount).toLocaleString()}</td>
              </tr>
            </tfoot>
          </table>
        </TableScroll>
      </Card>

      {/* timeline */}
      <h2 className="mb-3 text-sm font-semibold text-slate-500">TIMELINE</h2>
      <Card className="p-5">
        <ol className="space-y-4">
          <li className="flex gap-3">
            <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-slate-300" />
            <div>
              <div className="text-sm font-medium">Order created</div>
              <div className="text-xs text-slate-400">{new Date(order.created_at).toLocaleString()}</div>
            </div>
          </li>
          {order.events.map((e, i) => (
            <li key={i} className="flex gap-3">
              <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[var(--primary)]" />
              <div>
                <div className="text-sm font-medium">
                  {e.to_status.replace(/_/g, " ")}
                  {e.actor_name && <span className="font-normal text-slate-500"> — by {e.actor_name}</span>}
                </div>
                <div className="text-xs text-slate-400">{new Date(e.created_at).toLocaleString()}</div>
              </div>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

const INVOICEABLE = ["confirmed", "preparing", "dispatched", "delivered", "completed"];

/** The order's tax invoice: issued on delivery (or confirmation), or early from here. */
function InvoiceCard({ orderId, status, version, setError }: {
  orderId: string; status: string; version: number; setError: (s: string) => void;
}) {
  const { me } = useMe();
  const [inv, setInv] = useState<SalesInvoiceDetail | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const visible = can(me, "view_accounts");

  useEffect(() => {
    if (!visible) return;
    api(`/accounts/orders/${orderId}/invoice`).then(setInv).catch(() => setInv(null));
  }, [orderId, version, visible]);

  if (!visible || inv === undefined) return null;

  async function issue() {
    setBusy(true);
    setError("");
    try { setInv(await api(`/accounts/orders/${orderId}/invoice`, { method: "POST" })); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }

  if (inv === null) {
    if (!INVOICEABLE.includes(status)) return null;
    return (
      <Card className="mb-6 flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <FileText size={16} /> Not invoiced yet. The invoice is issued automatically when the order is delivered.
        </div>
        {can(me, "manage_accounts") && (
          <Button variant="outline" disabled={busy} onClick={issue}>{busy ? "Issuing…" : "Issue invoice now"}</Button>
        )}
      </Card>
    );
  }

  const badge = invoiceBadge(inv);
  const e = inv.einvoice ? edocBadge(inv.einvoice.status, inv.einvoice.flow) : null;
  return (
    <Card className="mb-6 flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="flex items-center gap-2">
          <FileText size={16} className="text-slate-400" />
          <span className="font-mono text-sm font-medium">{inv.number}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs ${badge.className}`}>{badge.label}</span>
          {e && inv.einvoice && (
            <span className={`rounded-full px-2 py-0.5 text-xs ${e.className}`}>ZATCA {FLOW_LABEL[inv.einvoice.flow]} · {e.label}</span>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {money(inv.currency, inv.total)} incl. {money(inv.currency, inv.vat_amount)} VAT · issued {day(inv.issue_date)} · due {day(inv.due_date)}
          {Number(inv.balance_due) > 0 && Number(inv.balance_due) < Number(inv.total) && <> · {money(inv.currency, inv.balance_due)} left to pay</>}
        </p>
      </div>
      <div className="flex gap-2">
        {inv.customer_id && <Link href={`/accounts/${inv.customer_id}`}><Button variant="ghost">Account</Button></Link>}
        <Button variant="outline" onClick={() => downloadFile(`/accounts/invoices/${inv.id}/pdf`, `${inv.number}.pdf`).catch((e) => setError(e.message))}>
          <Download size={16} /> PDF
        </Button>
      </div>
    </Card>
  );
}