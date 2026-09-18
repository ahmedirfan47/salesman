import AsyncStorage from "@react-native-async-storage/async-storage";

/**
 * Points at the deployed backend by default -- a phone can't reach a dev
 * machine's "localhost". Override with EXPO_PUBLIC_API_URL in app config
 * or a .env file if you need to point at a different environment.
 */
const API_BASE =
  process.env.EXPO_PUBLIC_API_URL || "https://salesman-backend-m5gx.onrender.com";

const TOKEN_KEY = "salesman_token";

export async function getToken(): Promise<string | null> {
  return AsyncStorage.getItem(TOKEN_KEY);
}
export async function setToken(token: string): Promise<void> {
  await AsyncStorage.setItem(TOKEN_KEY, token);
}
export async function clearToken(): Promise<void> {
  await AsyncStorage.removeItem(TOKEN_KEY);
}

export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

/**
 * Same shape as the dashboard's api() helper: attaches the bearer token,
 * throws UnauthorizedError on 401 (the caller/auth context decides what to
 * do -- e.g. sign the user out), and throws the backend's error detail
 * message on any other non-2xx response.
 */
export async function api(path: string, options: RequestInit = {}) {
  const token = await getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (res.status === 401) {
    await clearToken();
    throw new UnauthorizedError();
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
  await setToken(data.access_token);
  return data;
}

export type Me = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  capabilities: string[];
};

export async function fetchMe(): Promise<Me> {
  return api("/auth/me");
}

export function can(me: Me | null, capability: string): boolean {
  return !!me && me.capabilities.includes(capability);
}