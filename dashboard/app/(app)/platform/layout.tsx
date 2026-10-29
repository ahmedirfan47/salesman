"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Building2, CreditCard, Landmark, ServerCog, ToggleRight, Users } from "lucide-react";
import { useMe } from "@/lib/use-me";

const TABS = [
  { href: "/platform", label: "Overview", icon: BarChart3 },
  { href: "/platform/switches", label: "Switches", icon: ToggleRight },
  { href: "/platform/businesses", label: "Businesses", icon: Building2 },
  { href: "/platform/people", label: "People", icon: Users },
  { href: "/platform/billing", label: "Billing", icon: CreditCard },
  { href: "/platform/system", label: "System", icon: ServerCog },
  { href: "/platform/activity", label: "Activity", icon: Activity },
];

/** The Stonic Console: only the emails in PLATFORM_ADMIN_EMAILS get past this. */
export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const { me, loading } = useMe();
  const pathname = usePathname();

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!me?.is_platform_admin) return <p className="text-slate-400">Page not found.</p>;

  const active = (href: string) => (href === "/platform" ? pathname === "/platform" : pathname.startsWith(href));

  return (
    <div>
      <div className="mb-5">
        <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold">
          <Landmark size={22} className="text-[var(--primary)]" /> Stonic Console
        </h1>
        <p className="text-sm text-slate-500">Run Salesman for every business. Only Stonic staff see this.</p>
      </div>
      <nav className="-mx-4 mb-6 overflow-x-auto border-b border-[var(--border)] px-4 md:mx-0 md:px-0">
        <div className="flex min-w-max gap-1">
          {TABS.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition ${
                active(href) ? "border-[var(--primary)] text-[var(--primary)]" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}>
              <Icon size={15} /> {label}
            </Link>
          ))}
        </div>
      </nav>
      {children}
    </div>
  );
}