"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity, BarChart3, Building2, CreditCard, LogOut, Menu, ServerCog, ShieldCheck, ToggleRight, Users, X,
} from "lucide-react";
import { CONSOLE_LOGIN, consoleApi, consoleLogout, getAdminToken, SITE_CHANGED, type Admin } from "@/lib/console-api";
import { getSite, type SiteStatus } from "@/lib/api";
import { AdminContext } from "@/lib/use-admin";

const NAV = [
  { href: "/console", label: "Overview", icon: BarChart3, about: "How Salesman is being used, on the web and in the app." },
  { href: "/console/switches", label: "Switches", icon: ToggleRight, about: "Open or close sign-in and sign-up, read-only mode and the banner." },
  { href: "/console/businesses", label: "Businesses", icon: Building2, about: "Every business on Salesman. Suspend or reactivate one." },
  { href: "/console/people", label: "People", icon: Users, about: "Everyone with a Salesman account, in every business." },
  { href: "/console/billing", label: "Billing", icon: CreditCard, about: "Subscriptions and invoices for every business on Salesman." },
  { href: "/console/system", label: "System", icon: ServerCog, about: "Server, database, background jobs and integrations." },
  { href: "/console/activity", label: "Activity", icon: Activity, about: "What was changed from this console, and every sign-in." },
  { href: "/console/admins", label: "Admins", icon: ShieldCheck, about: "Who can sign in to this console." },
];

/** The Stonic Console: its own sign-in and its own shell, separate from the business dashboard. */
export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === CONSOLE_LOGIN) return <>{children}</>;
  return <ConsoleShell>{children}</ConsoleShell>;
}

function ConsoleShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!getAdminToken()) {
      router.replace(CONSOLE_LOGIN);
      return;
    }
    consoleApi("/platform/auth/me").then(setAdmin).catch((e) => setError(e.message));
  }, [router]);

  if (!admin) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">
        {error || "Loading…"}
      </div>
    );
  }

  const current = [...NAV].reverse().find((n) => (n.href === "/console" ? pathname === "/console" : pathname.startsWith(n.href)));

  return (
    <AdminContext.Provider value={{ admin, setAdmin }}>
      <div className="flex min-h-screen flex-col md:flex-row">
        {/* Mobile top bar */}
        <div className="sticky top-0 z-40 flex h-14 items-center justify-between bg-slate-900 px-4 text-white md:hidden">
          <Brand />
          <button onClick={() => setOpen(true)} aria-label="Open menu"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-300 hover:bg-white/10">
            <Menu size={22} />
          </button>
        </div>

        {/* Desktop sidebar */}
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-slate-900 text-slate-300 md:flex">
          <div className="px-6 py-5"><Brand /></div>
          <SidePanel admin={admin} pathname={pathname} />
        </aside>

        {/* Mobile drawer */}
        {open && (
          <div className="fixed inset-0 z-50 md:hidden">
            <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
            <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-slate-900 text-slate-300 shadow-xl">
              <div className="flex items-center justify-between px-6 py-5">
                <Brand />
                <button onClick={() => setOpen(false)} aria-label="Close menu"
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-300 hover:bg-white/10">
                  <X size={20} />
                </button>
              </div>
              <SidePanel admin={admin} pathname={pathname} onNavigate={() => setOpen(false)} />
            </div>
          </div>
        )}

        <main className="min-w-0 flex-1 p-4 md:p-8">
          {current && (
            <div className="mb-6">
              <h1 className="mb-1 text-2xl font-bold">{current.label}</h1>
              <p className="text-sm text-slate-500">{current.about}</p>
            </div>
          )}
          {children}
        </main>
      </div>
    </AdminContext.Provider>
  );
}

function Brand() {
  return (
    <Link href="/console" className="flex items-center gap-2 text-base font-bold tracking-tight text-white">
      <ShieldCheck size={20} className="text-indigo-400" /> Stonic Console
    </Link>
  );
}

function SidePanel({ admin, pathname, onNavigate }: { admin: Admin; pathname: string; onNavigate?: () => void }) {
  const active = (href: string) => (href === "/console" ? pathname === "/console" : pathname.startsWith(href));
  return (
    <>
      <div className="px-6 pb-3 text-xs text-slate-400">{admin.full_name || admin.email}</div>
      <SiteState pathname={pathname} onNavigate={onNavigate} />
      <nav className="flex-1 space-y-1 overflow-y-auto px-3">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} onClick={onNavigate}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
              active(href) ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
            }`}>
            <Icon size={18} /> {label}
          </Link>
        ))}
      </nav>
      <button onClick={consoleLogout}
        className="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-400 hover:bg-white/5 hover:text-slate-200">
        <LogOut size={18} /> Sign out
      </button>
    </>
  );
}

/** Whether the business app is open right now: checked on every page change and updated when the switches are saved. */
function SiteState({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  const [site, setSite] = useState<SiteStatus | null>(null);
  const load = useCallback(() => { getSite().then(setSite); }, []);
  useEffect(() => { load(); }, [load, pathname]);
  useEffect(() => {
    const changed = (e: Event) => {
      const detail = (e as CustomEvent<Partial<SiteStatus>>).detail;
      setSite((s) => (s ? { ...s, ...detail } : s));
    };
    window.addEventListener(SITE_CHANGED, changed);
    return () => window.removeEventListener(SITE_CHANGED, changed);
  }, []);
  if (!site) return null;

  const problems = [
    !site.sign_in_enabled && "Sign-in closed",
    site.sign_in_enabled && !site.sign_up_enabled && "Sign-up closed",
    site.read_only && "Read-only",
  ].filter(Boolean) as string[];
  const ok = problems.length === 0;

  return (
    <Link href="/console/switches" onClick={onNavigate}
      className={`mx-3 mb-4 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${
        ok ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/15 text-amber-300"
      }`}>
      <span className={`h-2 w-2 shrink-0 rounded-full ${ok ? "bg-emerald-400" : "bg-amber-400"}`} />
      {ok ? "Salesman is open" : problems.join(" · ")}
    </Link>
  );
}