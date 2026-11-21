// Types and labels for ERP integrations: Odoo, SAP Business One, Dynamics 365 Business Central.

export type ConnectField = { label: string; placeholder?: string; optional?: boolean; default?: string; advanced?: boolean };
export type Provider = { key: string; name: string; available: boolean; connect_fields: Record<string, ConnectField> };

/** Odoo and SAP price lists use numbers; SAP codes and Business Central ids are strings. */
export type Ref = number | string;

export type BranchMapping = { warehouse_id: Ref | null; pricelist_id: Ref | null };

export type ConnectionSettings = {
  company_id?: Ref | null;
  company_currency?: string;
  sales_journal_id?: Ref | null;
  taxes?: Record<string, Ref>;
  payment_journals?: Record<string, Ref>;
  adjustment_account?: Ref | null;
  aad_tenant?: string | null;
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
  api: string | null;
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

type Named = { id: Ref; name: string; company_id?: Ref | null };
export type Options = {
  version: string | null;
  api: string;
  companies: (Named & { currency: string | null })[];
  warehouses: (Named & { code: string })[];
  pricelists: (Named & { currency: string })[];
  journals: (Named & { type: "sale" | "bank" | "cash"; code: string })[];
  taxes: (Named & { amount: number | null; price_include: boolean })[];
  accounts?: Named[];
  labels?: Record<string, string>;
};

export type TestResult = {
  ok: boolean; kind: "ok" | "login" | "unreachable" | "refused"; message: string; latency_ms: number;
  version?: string | null; companies?: number | null; warehouses?: number | null; price_lists?: number | null;
  taxes?: number | null; problems: string[];
};

export type HealthCheck = { key: string; status: "ok" | "info" | "warning" | "error"; message: string };
export type Health = { status: "healthy" | "degraded" | "down" | "off"; checks: HealthCheck[]; checked_at: string };

export type DryRunBranch = {
  branch: string; products: number; new: number; price_changes: number; stock_changes: number;
  not_in_erp: string[]; not_in_erp_count: number;
  examples: { sku: string; kind: "new" | "price" | "stock"; from?: string | number; to?: string | number; price?: string; quantity?: number }[];
};
export type DryRun = { products: number; new_products: number; branches: DryRunBranch[]; notes: string[]; message: string | null };

export const PROVIDER_NAME: Record<string, string> = {
  odoo: "Odoo", sap_b1: "SAP Business One", dynamics_bc: "Business Central", zoho_books: "Zoho Books", qoyod: "Qoyod",
};

/** Where to get the login, per system. */
export const PROVIDER_HELP: Record<string, string> = {
  odoo: "In Odoo, open your profile › Preferences › Account Security and create an API key. Use a user who can manage sales, inventory and invoicing.",
  sap_b1: "Use the Service Layer address (usually port 50000) published over HTTPS, the company database name, and a SAP user with sales, inventory and banking authorisations.",
  dynamics_bc: "Register an app in Microsoft Entra with the Business Central API permission (API.ReadWrite.All), create a client secret, then add the app in Business Central under Microsoft Entra Applications and give it D365 BUS FULL ACCESS.",
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

export type Balance = {
  customer_id: string; name: string | null; salesman: string; odoo: string; erp?: string | null; difference: string; partner_id: Ref;
};

export const ACTION_LABEL: Record<string, string> = {
  "order.confirmed": "Sales order",
  "order.delivered": "Delivery",
  "order.cancelled": "Order cancelled",
  invoice: "Invoice",
  payment: "Payment",
  "payment.void": "Payment reversed",
  customer: "Customer",
  catalog: "Prices and stock",
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