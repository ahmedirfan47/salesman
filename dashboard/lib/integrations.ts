// Types and labels for ERP integrations (Odoo first).

export type Provider = { key: string; name: string; available: boolean };

export type BranchMapping = { warehouse_id: number | null; pricelist_id: number | null };

export type ConnectionSettings = {
  company_id?: number | null;
  company_currency?: string;
  sales_journal_id?: number | null;
  taxes?: Record<string, number>;
  payment_journals?: Record<string, number>;
  branches?: Record<string, BranchMapping>;
  push_orders?: boolean;
  validate_deliveries?: boolean;
  push_invoices?: boolean;
  push_payments?: boolean;
  pull_catalog?: boolean;
  pull_interval_minutes?: number;
};

export type Connection = {
  id: string;
  provider: string;
  status: "draft" | "active" | "paused";
  base_url: string;
  database: string | null;
  username: string | null;
  api: "json2" | "jsonrpc" | null;
  server_version: string | null;
  settings: ConnectionSettings;
  connected_at: string | null;
  last_pull_at: string | null;
  next_pull_at: string | null;
  last_error: string | null;
  created_at: string;
};

export type Counts = { ok: number; warning: number; failed: number; skipped: number };

export type Overview = { providers: Provider[]; connection: Connection | null; problems: string[]; counts: Counts };

type Named = { id: number; name: string; company_id?: number | null };
export type Options = {
  version: string | null;
  api: string;
  companies: (Named & { currency: string })[];
  warehouses: (Named & { code: string })[];
  pricelists: (Named & { currency: string })[];
  journals: (Named & { type: "sale" | "bank" | "cash"; code: string })[];
  taxes: (Named & { amount: number; price_include: boolean })[];
};

export type ConnectResult = { connection: Connection; options: Options; problems: string[] };

export type SyncEvent = {
  id: string;
  direction: "push" | "pull";
  action: string;
  local_key: string;
  label: string;
  status: "pending" | "ok" | "warning" | "failed" | "skipped";
  message: string | null;
  external_ref: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
};

export type Balance = { customer_id: string; name: string | null; salesman: string; odoo: string; difference: string; partner_id: number };

export const ACTION_LABEL: Record<string, string> = {
  "order.confirmed": "Sales order",
  "order.delivered": "Delivery",
  "order.cancelled": "Order cancelled",
  invoice: "Invoice",
  payment: "Payment",
  "payment.void": "Payment reversed",
  customer: "Customer",
  catalog: "Fetched from Odoo",
};

export const METHOD_LABEL: Record<string, string> = {
  cash: "Cash",
  bank_transfer: "Bank transfer",
  cheque: "Cheque",
  card: "Card",
  other: "Other",
};

export function statusBadge(status: string): { label: string; className: string } {
  switch (status) {
    case "ok":
      return { label: "Done", className: "bg-emerald-50 text-emerald-700" };
    case "warning":
      return { label: "Check", className: "bg-amber-50 text-amber-800" };
    case "failed":
      return { label: "Failed", className: "bg-red-50 text-red-700" };
    case "pending":
      return { label: "Queued", className: "bg-blue-50 text-blue-700" };
    case "skipped":
      return { label: "Skipped", className: "bg-gray-100 text-slate-600" };
    default:
      return { label: status, className: "bg-gray-100 text-slate-600" };
  }
}

export function connectionBadge(c: Connection | null): { label: string; className: string } {
  if (!c) return { label: "Not connected", className: "bg-gray-100 text-slate-600" };
  if (c.status === "active") return c.last_error
    ? { label: "Needs attention", className: "bg-red-50 text-red-700" }
    : { label: "Syncing", className: "bg-emerald-50 text-emerald-700" };
  if (c.status === "paused") return { label: "Paused", className: "bg-gray-100 text-slate-600" };
  return { label: "Not switched on", className: "bg-amber-50 text-amber-800" };
}

export function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}