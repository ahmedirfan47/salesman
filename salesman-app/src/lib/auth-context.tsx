import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  clearToken,
  fetchMe,
  getToken,
  login as apiLogin,
  type Me,
} from "./api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-fetches /auth/me -- call after any action that might change role/capabilities. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      setMe(null);
      return;
    }
    try {
      setMe(await fetchMe());
    } catch {
      // token invalid/expired -- api() already cleared it on a 401
      setMe(null);
    }
  }, []);

  useEffect(() => {
    loadMe().finally(() => setLoading(false));
  }, [loadMe]);

  async function login(email: string, password: string) {
    await apiLogin(email, password);
    await loadMe();
  }

  async function logout() {
    await clearToken();
    setMe(null);
  }

  return (
    <AuthContext.Provider value={{ me, loading, login, logout, refresh: loadMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}