// dashboard\lib\use-admin.ts
"use client";

import { createContext, useContext } from "react";
import type { Admin } from "@/lib/console-api";

export type AdminState = { admin: Admin; setAdmin: (a: Admin) => void };
export const AdminContext = createContext<AdminState | null>(null);

/** The signed-in console admin. Only usable inside the Stonic Console pages. */
export function useAdmin(): AdminState {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdmin is only available in the Stonic Console");
  return ctx;
}