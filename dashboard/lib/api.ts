//dashboard\lib\api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---- Preview mode -------------------------------------------------------------------------
// NEXT_PUBLIC_PREVIEW_MODE=on (set in Vercel, then redeploy): no sign-in and no backend.
// Everyone lands in the dashboard as the read-only demo business, with the sample data in
// public/preview/data.json (made by `python -m app.scripts.export_preview`). Changes are off.
export const PREVIEW = process.env.NEXT_PUBLIC_PREVIEW_MODE === "on";
export const PREVIEW_MESSAGE = "This is a preview with sample data. Changes are switched off.";

type Snapshot = Record<string, { status: number; body: unknown }>;
let snapshot: Promise<Snapshot> | null = null;

function loadSnapshot(): Promise<Snapshot> {
  snapshot ??= fetch("/preview/data.json")
    .then((r) => (r.ok ? r.json() : { responses: {} }))
    .then((d) => (d.responses ?? {}) as Snapshot)
    .catch(() => ({}));
  return snapshot;
}

/** The saved answer for a GET: the exact address, else the same page with other filters or dates. */
async function previewGet(path: string): Promise<unknown> {
  const data = await loadSnapshot();
  const clean = path.endsWith("?") ? path.slice(0, -1) : path;
  const base = clean.split("?")[0];
  const hit = data[clean] ?? data[base] ?? Object.entries(data).find(([k]) => k.split("?")[0] === base)?.[1];
  if (!hit) throw new Error("This part isn't available in the preview.");
  if (hit.status >= 400) {
    const detail = (hit.body as { detail?: unknown } | null)?.detail;
    throw new Error(typeof detail === "string" ? detail : "This part isn't available in the preview.");
  }
  return structuredClone(hit.body);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  if (PREVIEW) return "preview"; // everyone is "signed in" as the demo business
  return localStorage.getItem("salesman_token");
}
export function setToken(t: string) {
  localStorage.setItem("salesman_token", t);
}
export function clearToken() {
  localStorage.removeItem("salesman_token");
  localStorage.removeItem(BRANCH_KEY);
}

// The branch an owner/admin is looking at ("" = all branches). Sent on every
// request; the server ignores it for branch staff, who only see their branch.
const BRANCH_KEY = "salesman_branch";
export function getBranchId(): string {
  if (typeof window === "undefined") return "";
  try { return localStorage.getItem(BRANCH_KEY) || ""; } catch { return ""; }
}
export function setBranchId(id: string) {
  try {
    if (id) localStorage.setItem(BRANCH_KEY, id);
    else localStorage.removeItem(BRANCH_KEY);
  } catch { /* storage unavailable: the choice lasts for this page only */ }
}
function branchHeader(): Record<string, string> {
  const id = getBranchId();
  return id ? { "X-Branch-Id": id } : {};
}
// Tells the server this request comes from the web dashboard (the app sends "mobile"),
// so the Stonic Console can show web and app usage separately.
const CLIENT_HEADER = { "X-Client": "web" };

/** Shown when the Salesman server can't be reached (switched off, asleep or no connection). */
export const OFFLINE_MESSAGE = "Salesman is offline right now. Please check back soon.";

/** fetch, with a readable message instead of "Failed to fetch" when the server can't be reached. */
export async function reach(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error(OFFLINE_MESSAGE);
  }
}

export async function api(path: string, options: RequestInit = {}) {
  if (PREVIEW) {
    if ((options.method ?? "GET").toUpperCase() !== "GET") throw new Error(PREVIEW_MESSAGE);
    return previewGet(path);
  }
  const token = getToken();
  const res = await reach(`${API_BASE}/api/v1${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...branchHeader(),
      ...CLIENT_HEADER,
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function login(email: string, password: string) {
  if (PREVIEW) return {};
  const res = await reach(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CLIENT_HEADER },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Login failed");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}
export async function uploadFile(path: string, file: File) {
  if (PREVIEW) throw new Error(PREVIEW_MESSAGE);
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const res = await reach(`${API_BASE}/api/v1${path}`, {
    method: "POST",
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...branchHeader(), ...CLIENT_HEADER }, // no Content-Type: browser sets multipart boundary
    body: form,
  });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Upload failed (${res.status})`);
  }
  return res.json();
}
/** Download a file from the API (PDFs etc.) with the same auth and branch headers as api(). */
export async function downloadFile(path: string, filename: string) {
  if (PREVIEW) throw new Error("Downloads aren't available in the preview.");
  const token = getToken();
  const res = await reach(`${API_BASE}/api/v1${path}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...branchHeader(), ...CLIENT_HEADER },
  });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Download failed (${res.status})`);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type Me = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  capabilities: string[];
  branch_id: string | null;
  branch_name: string | null;
  sees_all_branches: boolean;
  /** "ok" | "open" | "overdue" | "read_only" */
  billing_state: string;
  billing_message: string | null;
};

export async function fetchMe(): Promise<Me> {
  return api("/auth/me");
}
export async function register(tenant_name: string, email: string, password: string) {
  if (PREVIEW) throw new Error(PREVIEW_MESSAGE);
  const res = await reach(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CLIENT_HEADER },
    body: JSON.stringify({ tenant_name, email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Registration failed");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

/** Whether sign-in and sign-up are open, and the banner (set in the Stonic Console). No sign-in needed. */
export type SiteStatus = {
  sign_in_enabled: boolean;
  sign_up_enabled: boolean;
  read_only: boolean;
  closed_message: string | null;
  read_only_message: string | null;
  banner_text: string | null;
  banner_tone: "info" | "warning";
  /** true when the server couldn't be reached at all */
  offline?: boolean;
};

// The server can't be reached: treat sign-in and sign-up as closed, so visitors
// see a clear notice instead of a form that can only fail.
const SITE_OFFLINE: SiteStatus = {
  sign_in_enabled: false, sign_up_enabled: false, read_only: false, closed_message: OFFLINE_MESSAGE,
  read_only_message: null, banner_text: null, banner_tone: "info", offline: true,
};

// What the pages see in preview mode: everything open, no notices.
const SITE_PREVIEW: SiteStatus = {
  sign_in_enabled: true, sign_up_enabled: false, read_only: false, closed_message: null,
  read_only_message: null, banner_text: null, banner_tone: "info",
};

export async function getSite(): Promise<SiteStatus> {
  if (PREVIEW) return SITE_PREVIEW;
  try {
    const res = await fetch(`${API_BASE}/api/v1/site`, { cache: "no-store" });
    return res.ok ? await res.json() : SITE_OFFLINE;
  } catch {
    return SITE_OFFLINE;
  }
}