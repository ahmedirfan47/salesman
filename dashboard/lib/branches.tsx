"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getBranchId, setBranchId } from "@/lib/api";
import { useMe } from "@/lib/use-me";

export type Branch = {
  id: string;
  name: string;
  city: string | null;
  address: string | null;
  is_default: boolean;
  is_active: boolean;
  whatsapp_phone_number_id: string | null;
  whatsapp_display_number: string | null;
  whatsapp_update_template: string | null;
  whatsapp_connected: boolean;
  order_updates_enabled: boolean;
  created_at: string;
};

type Ctx = {
  branches: Branch[];
  /** branch being viewed; "" = all branches (owners/admins only) */
  current: string;
  setCurrent: (id: string) => void;
  /** owners/admins can switch; branch staff are fixed to their branch */
  canSwitch: boolean;
  nameOf: (id: string | null | undefined) => string;
  reload: () => Promise<void>;
};

const BranchContext = createContext<Ctx>({
  branches: [], current: "", setCurrent: () => {}, canSwitch: false, nameOf: () => "", reload: async () => {},
});

export function BranchProvider({ children }: { children: React.ReactNode }) {
  const { me } = useMe();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [current, setCurrentState] = useState(() => getBranchId());
  const canSwitch = !!me?.sees_all_branches;

  const reload = useCallback(async () => {
    try {
      setBranches(await api("/branches"));
    } catch {
      setBranches([]);
    }
  }, []);

  useEffect(() => {
    if (!me) return;
    reload();
    setCurrentState(me.sees_all_branches ? getBranchId() : me.branch_id ?? "");
  }, [me, reload]);

  // forget a remembered branch that no longer exists or is switched off
  useEffect(() => {
    if (canSwitch && current && branches.length && !branches.some((b) => b.id === current && b.is_active)) {
      setBranchId("");
      setCurrentState("");
    }
  }, [branches, current, canSwitch]);

  const setCurrent = useCallback((id: string) => {
    setBranchId(id);
    setCurrentState(id);
  }, []);

  const nameOf = useCallback(
    (id: string | null | undefined) => branches.find((b) => b.id === id)?.name ?? "",
    [branches],
  );

  return (
    <BranchContext.Provider value={{ branches, current, setCurrent, canSwitch, nameOf, reload }}>
      {children}
    </BranchContext.Provider>
  );
}

export function useBranches() {
  return useContext(BranchContext);
}

/** True when an owner/admin is looking at all branches and there is more than one. */
export function useAllBranchesView() {
  const { current, canSwitch, branches } = useBranches();
  return canSwitch && !current && branches.filter((b) => b.is_active).length > 1;
}