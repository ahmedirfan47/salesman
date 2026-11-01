"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Info, Lock } from "lucide-react";
import { getSite, type SiteStatus } from "@/lib/api";

/** The announcement banner and read-only notice set in the Stonic Console, on every signed-in page. */
export function SiteBanner() {
  const [site, setSite] = useState<SiteStatus | null>(null);

  useEffect(() => {
    getSite().then(setSite);
  }, []);

  if (!site) return null;
  const notices: React.ReactNode[] = [];

  if (site.read_only && site.read_only_message) {
    notices.push(
      <div key="ro" className="mb-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <Lock size={16} className="mt-0.5 shrink-0" />
        <span>{site.read_only_message}</span>
      </div>,
    );
  }
  if (site.banner_text) {
    const warning = site.banner_tone === "warning";
    notices.push(
      <div key="banner" className={`mb-3 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${
        warning ? "border-amber-200 bg-amber-50 text-amber-900" : "border-indigo-100 bg-indigo-50 text-slate-700"
      }`}>
        {warning ? <AlertTriangle size={16} className="mt-0.5 shrink-0" /> : <Info size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />}
        <span>{site.banner_text}</span>
      </div>,
    );
  }
  return notices.length ? <div className="mb-3">{notices}</div> : null;
}