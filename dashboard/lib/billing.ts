// Types and helpers shared by the Billing & Plan page and the Stonic console.

export type InvoiceLine = { description: string; quantity: string; unit_amount: string; amount: string };

export type Invoice = {
  id: string;
  number: string;
  kind: "setup" | "subscription" | "other";
  status: "open" | "paid" | "void";
  currency: string;
  lines: InvoiceLine[];
  subtotal: string;
  tax_percent: string;
  tax_amount: string;
  total: string;
  bill_to: { name?: string; address?: string | null; tax_id?: string | null; email?: string | null };
  issued_on: string;
  due_on: string;
  period_start: string | null;
  period_end: string | null;
  paid_on: string | null;
  payment_reference: string | null;
  voided_on: string | null;
  void_reason: string | null;
  notes: string | null;
};

export type Subscription = {
  status: "active" | "paused" | "cancelled";
  currency: string;
  setup_fee_per_branch: string;
  monthly_fee_per_branch: string;
  tax_percent: string;
  payment_terms_days: number;
  grace_days: number;
  next_invoice_on: string;
  setup_billed_branches: number;
  billing_name: string | null;
  billing_address: string | null;
  billing_tax_id: string | null;
  billing_email: string | null;
  notes: string | null;
  cancelled_on: string | null;
};

export type AccountState = {
  state: "ok" | "open" | "overdue" | "read_only";
  read_only: boolean;
  open_invoices: number;
  outstanding: string;
  overdue: string;
  currency: string;
  oldest_invoice: string | null;
  oldest_due_on: string | null;
  read_only_from: string | null;
  message: string | null;
};

export function money(currency: string, value: string | number): string {
  const n = Number(value);
  return `${currency} ${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-09" -> "9 Nov 2026", the same format the invoices and server messages use. */
export function day(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function isOverdue(inv: Invoice): boolean {
  return inv.status === "open" && inv.due_on < new Date().toISOString().slice(0, 10);
}

export function statusBadge(inv: Invoice): { label: string; className: string } {
  if (inv.status === "paid") return { label: "Paid", className: "bg-emerald-50 text-emerald-700" };
  if (inv.status === "void") return { label: "Void", className: "bg-gray-100 text-gray-500" };
  if (isOverdue(inv)) return { label: "Overdue", className: "bg-red-50 text-red-700" };
  return { label: "Unpaid", className: "bg-amber-50 text-amber-700" };
}

export const KIND_LABEL: Record<Invoice["kind"], string> = {
  setup: "Setup",
  subscription: "Monthly",
  other: "Other",
};

export const STATE_LABEL: Record<AccountState["state"], { label: string; className: string }> = {
  ok: { label: "Paid up", className: "bg-emerald-50 text-emerald-700" },
  open: { label: "Invoice due", className: "bg-amber-50 text-amber-700" },
  overdue: { label: "Overdue", className: "bg-red-50 text-red-700" },
  read_only: { label: "Read-only", className: "bg-red-100 text-red-800" },
};