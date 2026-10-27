// Types and helpers for customer accounts (receivables, invoices, payments, statements).
import type { EInvoiceSummary } from "@/lib/zatca";
export { money, day } from "@/lib/billing";

export type Aging = {
  current: string;
  days_1_30: string;
  days_31_60: string;
  days_61_90: string;
  days_90_plus: string;
};

export const AGING_LABELS: { key: keyof Aging; label: string }[] = [
  { key: "current", label: "Not yet due" },
  { key: "days_1_30", label: "1–30 days" },
  { key: "days_31_60", label: "31–60 days" },
  { key: "days_61_90", label: "61–90 days" },
  { key: "days_90_plus", label: "Over 90 days" },
];

export type AccountRow = {
  customer_id: string;
  name: string;
  company: string | null;
  branch_id: string;
  whatsapp_number: string | null;
  currency: string;
  balance: string;
  uninvoiced: string;
  exposure: string;
  credit_limit: string | null;
  available_credit: string | null;
  over_limit: boolean;
  payment_terms_days: number;
  on_hold: boolean;
  overdue: string;
  oldest_overdue_days: number;
  blocking_overdue: string;
  unapplied: string;
  open_invoices: number;
  aging: Aging;
};

export type AccountTotals = {
  currency: string;
  receivable: string;
  overdue: string;
  customers_overdue: number;
  customers_over_limit: number;
  customers_on_hold: number;
  unapplied: string;
  aging: Aging;
};

export type SalesInvoice = {
  id: string;
  branch_id: string;
  customer_id: string | null;
  order_id: string | null;
  original_invoice_id: string | null;
  kind: "invoice" | "credit_note" | "opening_balance";
  number: string;
  issue_date: string;
  due_date: string;
  currency: string;
  subtotal: string;
  vat_amount: string;
  total: string;
  amount_paid: string;
  amount_credited: string;
  balance_due: string;
  status: "open" | "partially_paid" | "paid" | "issued";
  buyer: { name?: string; company?: string | null; vat_number?: string | null; phone?: string | null };
  reason: string | null;
  created_at: string;
  einvoice: EInvoiceSummary | null;
};

export type InvoiceLine = {
  sku: string | null; name: string; quantity: string; unit_price: string; net: string; vat_rate: string; vat: string; total: string;
};

export type SalesInvoiceDetail = SalesInvoice & {
  lines: InvoiceLine[];
  notes: string | null;
  payments: { payment_id: string; payment_number: string; paid_on: string; method: string; amount: string }[];
  credit_notes: SalesInvoice[];
};

export type Payment = {
  id: string;
  branch_id: string;
  customer_id: string | null;
  number: string;
  amount: string;
  currency: string;
  method: "cash" | "bank_transfer" | "cheque" | "card" | "other";
  reference: string | null;
  paid_on: string;
  notes: string | null;
  unallocated: string;
  voided_at: string | null;
  void_reason: string | null;
  created_at: string;
};

export type AccountSettings = {
  currency: string;
  vat_rate: string;
  prices_include_vat: boolean;
  invoice_on: "confirmed" | "delivered";
  default_payment_terms_days: number;
  default_credit_limit: string | null;
  hold_over_limit: boolean;
  hold_when_overdue: boolean;
  overdue_grace_days: number;
  seller_name: string | null;
  seller_name_ar: string | null;
  seller_vat_number: string | null;
  seller_cr_number: string | null;
  seller_address: string | null;
  seller_street: string | null;
  seller_building_number: string | null;
  seller_district: string | null;
  seller_city: string | null;
  seller_postal_code: string | null;
  invoice_footer: string | null;
};

/** A customer's tax registration and national address (B2B e-invoices need them). */
export type TaxDetails = {
  vat_number: string | null;
  cr_number: string | null;
  street: string | null;
  building_number: string | null;
  district: string | null;
  city: string | null;
  postal_code: string | null;
};

export type StatementLine = {
  date: string; kind: string; document_number: string; description: string;
  debit: string; credit: string; balance: string; invoice_id: string | null; payment_id: string | null;
};

export type Statement = {
  customer: { id: string; name: string };
  currency: string;
  start: string;
  end: string;
  opening_balance: string;
  total_debits: string;
  total_credits: string;
  closing_balance: string;
  lines: StatementLine[];
};

export const METHOD_LABEL: Record<Payment["method"], string> = {
  cash: "Cash",
  bank_transfer: "Bank transfer",
  cheque: "Cheque",
  card: "Card",
  other: "Other",
};

export const KIND_LABEL: Record<SalesInvoice["kind"], string> = {
  invoice: "Invoice",
  credit_note: "Credit note",
  opening_balance: "Opening balance",
};

export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function invoiceBadge(inv: SalesInvoice): { label: string; className: string } {
  if (inv.kind === "credit_note") return { label: "Credit note", className: "bg-violet-50 text-violet-700" };
  if (inv.status === "paid") return { label: "Paid", className: "bg-emerald-50 text-emerald-700" };
  const overdue = inv.due_date < today();
  if (overdue) return { label: "Overdue", className: "bg-red-50 text-red-700" };
  if (inv.status === "partially_paid") return { label: "Part paid", className: "bg-amber-50 text-amber-700" };
  return { label: "Unpaid", className: "bg-amber-50 text-amber-700" };
}

/** Badges for a customer row: on hold, over limit, overdue. */
export function accountFlags(a: AccountRow): { label: string; className: string }[] {
  const flags = [];
  if (a.on_hold) flags.push({ label: "On hold", className: "bg-red-100 text-red-800" });
  if (a.over_limit) flags.push({ label: "Over limit", className: "bg-red-50 text-red-700" });
  if (Number(a.overdue) > 0) flags.push({ label: `Overdue ${a.oldest_overdue_days}d`, className: "bg-amber-50 text-amber-700" });
  return flags;
}