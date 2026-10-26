//dashboard\lib\api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
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

export async function api(path: string, options: RequestInit = {}) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...branchHeader(),
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
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    method: "POST",
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...branchHeader() }, // no Content-Type: browser sets multipart boundary
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
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...branchHeader() },
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
  is_platform_admin: boolean;
};

export async function fetchMe(): Promise<Me> {
  return api("/auth/me");
}
export async function register(tenant_name: string, email: string, password: string) {
  const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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