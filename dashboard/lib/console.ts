// Types and helpers for the Stonic Console (/platform).

export type SiteSettings = {
  sign_in_enabled: boolean;
  sign_up_enabled: boolean;
  read_only: boolean;
  closed_message: string;
  read_only_message: string;
  banner_text: string;
  banner_tone: "info" | "warning";
};

export type SettingsResponse = {
  settings: SiteSettings;
  effective: { sign_in_enabled: boolean; sign_up_enabled: boolean; read_only: boolean };
  updated_at: string | null;
  updated_by: string | null;
  admin_emails: string[];
};

export type SeriesPoint = {
  day: string;
  active: number;
  web: number;
  mobile: number;
  sign_ins: number;
  orders: number;
  messages: number;
  new_businesses: number;
};

export type Overview = {
  days: number;
  start: string;
  end: string;
  totals: {
    businesses: number; businesses_suspended: number; people: number; branches: number; customers: number;
    products: number; orders: number; conversations: number; online_now: number;
  };
  period: {
    active_people: number; web_people: number; mobile_people: number; sign_ins: number; failed_sign_ins: number;
    new_businesses: number; new_people: number; orders: number; order_value: { currency: string; amount: string }[];
    messages_in: number; messages_out: number;
  };
  series: SeriesPoint[];
  top_businesses: { id: string; name: string; orders: number; active_people: number; last_active_at: string | null }[];
};

export type BusinessRow = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  suspended_at: string | null;
  suspended_reason: string | null;
  owner_email: string | null;
  people: number;
  active_people_7d: number;
  branches: number;
  customers: number;
  orders: number;
  orders_30d: number;
  last_active_at: string | null;
};

export type Person = {
  id: string;
  tenant_id: string;
  business: string | null;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  branch: string | null;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
  is_platform_admin: boolean;
};

export type SignIn = {
  id: string;
  at: string;
  email: string;
  business: string | null;
  client: string;
  success: boolean;
  reason: string;
  ip: string | null;
};

export type BusinessDetail = {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  created_at: string;
  suspended_at: string | null;
  suspended_reason: string | null;
  counts: { customers: number; products: number; orders: number; orders_30d: number; invoices: number; conversations: number };
  people: Person[];
  branches: {
    id: string; name: string; city: string | null; is_default: boolean; is_active: boolean;
    whatsapp_connected: boolean; whatsapp_number: string | null; zatca: string | null; zatca_environment: string | null;
  }[];
  erp: { provider: string; status: string; server_version: string | null; last_pull_at: string | null; last_error: string | null } | null;
  sign_ins: SignIn[];
};

export type JobKind = { kind: string; queued: number; running: number; failed: number; done_24h: number };
export type FailedJob = {
  id: string; kind: string; business: string | null; attempts: number; max_attempts: number;
  last_error: string; finished_at: string | null; created_at: string;
};
export type ConfigItem = { key: string; ok: boolean; note: string };

export type SystemStatus = {
  checked_at: string;
  server: { environment: string; version: string; python: string; started_at: string; uptime_seconds: number; worker_enabled: boolean };
  database: { ok: boolean; latency_ms?: number; size_mb?: number; version?: string; error?: string };
  jobs: { kinds: JobKind[]; oldest_waiting_seconds: number; failed: FailedJob[] };
  zatca: {
    documents: Record<"queued" | "cleared" | "reported" | "rejected" | "blocked", number>;
    units: Record<string, number>;
    expiring: { business: string; branch: string; environment: string; expires_at: string }[];
  };
  erp: { business: string; provider: string; status: string; server_version: string | null; last_pull_at: string | null; last_error: string | null; failed_7d: number }[];
  whatsapp: { branches: number; connected: number; messages_in_24h: number; messages_out_24h: number; last_inbound_at: string | null };
  config: ConfigItem[];
};

export type AuditEntry = {
  id: string;
  created_at: string;
  actor_email: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_label: string | null;
  detail: Record<string, unknown>;
};

export const ROLES = ["owner", "admin", "salesman", "dispatcher", "driver", "warehouse", "viewer"] as const;

export const ACTION_LABEL: Record<string, string> = {
  "site.settings": "Changed site switches",
  "business.suspend": "Suspended a business",
  "business.reactivate": "Reactivated a business",
  "person.update": "Changed a person",
  "person.password": "Set a new password",
  "person.sign_out": "Signed someone out everywhere",
  "job.retry": "Retried a background job",
  "job.discard": "Discarded a background job",
};

export const SIGN_IN_REASON: Record<string, string> = {
  ok: "Signed in",
  wrong_password: "Wrong password",
  unknown_email: "Unknown email",
  inactive: "Account switched off",
  suspended: "Business suspended",
  sign_in_closed: "Sign-in closed",
};

export const CLIENT_LABEL: Record<string, string> = { web: "Web", mobile: "App", api: "API" };

export const JOB_LABEL: Record<string, string> = {
  "whatsapp.inbound_text": "WhatsApp message in",
  "whatsapp.inbound_audio": "WhatsApp voice note in",
  "whatsapp.send_text": "WhatsApp reply",
  "whatsapp.order_update": "WhatsApp order update",
  "whatsapp.send_document": "WhatsApp document",
  "zatca.submit": "ZATCA submission",
  "erp.push": "Send to ERP",
  "erp.pull": "Fetch from ERP",
};

/** "3 min ago", "2 h ago", "5 days ago", or a date. */
export function ago(iso: string | null): string {
  if (!iso) return "Never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} day${Math.floor(s / 86400) === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
  return `${Math.floor(seconds / 86400)} d ${Math.floor((seconds % 86400) / 3600)} h`;
}

export function num(n: number): string {
  return n.toLocaleString();
}