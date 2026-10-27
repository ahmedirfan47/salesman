// Types and labels for ZATCA e-invoicing (Fatoora Phase 2).

export type ComplianceResult = {
  label: string;
  status: "PASS" | "WARNING" | "ERROR" | string;
  errors: Message[];
  warnings: Message[];
};

export type Message = { code: string | null; message: string | null; category?: string | null };

export type ZatcaUnit = {
  id: string;
  branch_id: string;
  environment: "sandbox" | "simulation" | "production";
  status: "draft" | "active" | "failed" | "disabled";
  common_name: string;
  egs_serial: string;
  invoice_types: "1100" | "1000" | "0100";
  location: string;
  industry: string;
  icv: number;
  has_compliance_certificate: boolean;
  compliance_results: ComplianceResult[];
  certificate_expires_at: string | null;
  onboarded_at: string | null;
  last_error: string | null;
  created_at: string;
};

export type ZatcaCounts = { cleared: number; reported: number; waiting: number; rejected: number; blocked: number };

export type ZatcaOverview = { seller_problems: string[]; units: ZatcaUnit[]; counts: ZatcaCounts };

export type EDocStatus = "blocked" | "queued" | "cleared" | "reported" | "rejected" | "superseded";

export type EDocument = {
  id: string;
  branch_id: string;
  invoice_id: string;
  invoice_number: string;
  customer_id: string | null;
  buyer_name: string | null;
  issue_date: string;
  currency: string;
  total: string;
  flow: "standard" | "simplified";
  kind: "invoice" | "credit_note";
  status: EDocStatus;
  icv: number | null;
  document_uuid: string | null;
  invoice_hash: string | null;
  zatca_status: string | null;
  errors: Message[];
  warnings: Message[];
  last_error: string | null;
  attempts: number;
  signed_at: string | null;
  submitted_at: string | null;
  created_at: string;
  has_cleared_xml: boolean;
};

export type EInvoiceSummary = { document_id: string; flow: "standard" | "simplified"; status: EDocStatus };

export const ENV_LABEL: Record<ZatcaUnit["environment"], string> = {
  sandbox: "Developer sandbox",
  simulation: "Simulation",
  production: "Production",
};

export const TYPES_LABEL: Record<ZatcaUnit["invoice_types"], string> = {
  "1100": "B2B and B2C (standard and simplified)",
  "1000": "B2B only (standard)",
  "0100": "B2C only (simplified)",
};

export const FLOW_LABEL: Record<EDocument["flow"], string> = { standard: "B2B", simplified: "B2C" };

export function edocBadge(status: EDocStatus | string, flow?: string): { label: string; className: string } {
  switch (status) {
    case "cleared":
      return { label: "Cleared", className: "bg-emerald-50 text-emerald-700" };
    case "reported":
      return { label: "Reported", className: "bg-emerald-50 text-emerald-700" };
    case "queued":
      return { label: flow === "standard" ? "Clearing" : "Reporting", className: "bg-blue-50 text-blue-700" };
    case "rejected":
      return { label: "Rejected", className: "bg-red-50 text-red-700" };
    case "blocked":
      return { label: "Needs details", className: "bg-amber-50 text-amber-800" };
    case "superseded":
      return { label: "Replaced", className: "bg-gray-100 text-slate-500" };
    default:
      return { label: status, className: "bg-gray-100 text-slate-600" };
  }
}

export function unitBadge(u: ZatcaUnit | undefined): { label: string; className: string } {
  if (!u) return { label: "Not connected", className: "bg-gray-100 text-slate-600" };
  if (u.status === "active") return { label: "Connected", className: "bg-emerald-50 text-emerald-700" };
  if (u.status === "disabled") return { label: "Turned off", className: "bg-gray-100 text-slate-600" };
  if (u.status === "failed") return { label: "Needs attention", className: "bg-red-50 text-red-700" };
  return { label: u.has_compliance_certificate ? "Checks pending" : "Waiting for OTP", className: "bg-amber-50 text-amber-800" };
}