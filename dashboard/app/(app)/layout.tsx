"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";
import { MeProvider } from "@/lib/use-me";
import { BranchProvider, useBranches } from "@/lib/branches";
import Sidebar from "@/components/sidebar";
import { DemoBanner } from "@/components/demo-banner";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
    } else {
      setReady(true);
    }
  }, [router]);

  if (!ready) return null;

  return (
    <MeProvider>
      <BranchProvider>
        <div className="flex min-h-screen flex-col md:flex-row">
          <Sidebar />
          <main className="flex-1 overflow-auto p-4 md:p-8">
            <DemoBanner />
            <BranchScoped>{children}</BranchScoped>
          </main>
        </div>
      </BranchProvider>
    </MeProvider>
  );
}

/** Remounts the page when the branch changes, so every screen reloads its data for that branch. */
function BranchScoped({ children }: { children: React.ReactNode }) {
  const { current } = useBranches();
  return <div key={current || "all"}>{children}</div>;
}