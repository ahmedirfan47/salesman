//dashboard\lib\use-me.tsx
"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { fetchMe, Me } from "@/lib/api";

const MeContext = createContext<{ me: Me | null; loading: boolean }>({ me: null, loading: true });

export function MeProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetchMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);
  return <MeContext.Provider value={{ me, loading }}>{children}</MeContext.Provider>;
}

export function useMe() {
  return useContext(MeContext);
}

export function can(me: Me | null, cap: string): boolean {
  return !!me && me.capabilities.includes(cap);
}