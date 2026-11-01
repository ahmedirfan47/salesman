// dashboard\lib\console-api.ts
// The Stonic Console talks to the same API as the business app, with its own
// admin session. Business sign-ins and console sign-ins never share a token.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "stonic_admin_token";
export const CONSOLE_LOGIN = "/console/login";
/** Sent on window after the site switches are saved, so the sidebar shows the new state at once. */
export const SITE_CHANGED = "stonic:site-changed";

export type Admin = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
};

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setAdminToken(t: string) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ }
}
export function clearAdminToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
}

function headers(json: boolean): Record<string, string> {
  const token = getAdminToken();
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function signedOut(): never {
  clearAdminToken();
  if (typeof window !== "undefined" && window.location.pathname !== CONSOLE_LOGIN) {
    window.location.href = CONSOLE_LOGIN;
  }
  throw new Error("Your console session has ended. Sign in again.");
}

async function failure(res: Response, fallback: string): Promise<never> {
  const body = await res.json().catch(() => ({}));
  throw new Error(typeof body.detail === "string" ? body.detail : `${fallback} (${res.status})`);
}

/** A request to the console API with the admin session. 401 goes back to the console sign-in page. */
export async function consoleApi(path: string, options: RequestInit = {}) {
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    ...options,
    headers: { ...headers(true), ...(options.headers || {}) },
  });
  if (res.status === 401) signedOut();
  if (!res.ok) await failure(res, "Request failed");
  if (res.status === 204) return null;
  return res.json();
}

/** Download a file (invoice PDFs) with the admin session. */
export async function consoleDownload(path: string, filename: string) {
  const res = await fetch(`${API_BASE}/api/v1${path}`, { headers: headers(false) });
  if (res.status === 401) signedOut();
  if (!res.ok) await failure(res, "Download failed");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function consoleLogin(email: string, password: string): Promise<Admin> {
  const res = await fetch(`${API_BASE}/api/v1/platform/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) await failure(res, "Sign-in failed");
  const data = await res.json();
  setAdminToken(data.access_token);
  return data.admin;
}

export function consoleLogout() {
  clearAdminToken();
  if (typeof window !== "undefined") window.location.href = CONSOLE_LOGIN;
}