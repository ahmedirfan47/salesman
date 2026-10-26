"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard, Package, Tag, ShoppingCart, AlertTriangle,
  FileBarChart, Printer, MessageSquare, Users, MapPin, ClipboardList,
  Truck, Contact, CreditCard, LogOut, Menu, X, TrendingUp, Target, Building2, Landmark,
} from "lucide-react";
import { clearToken } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { BranchSwitcher } from "@/components/branch-switcher";

const nav = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard, cap: null },
  { href: "/products", label: "Products", icon: Package, cap: null },
  { href: "/customers", label: "Customers", icon: Contact, cap: "manage_users" },
  { href: "/prospects", label: "Prospects", icon: Target, cap: "manage_prospects" },
  { href: "/pricing", label: "Pricing", icon: Tag, cap: "manage_pricing" },
  { href: "/orders", label: "Orders", icon: ShoppingCart, cap: "view_orders" },
  { href: "/assignments", label: "Assignments", icon: ClipboardList, cap: "dispatch_order" },
  { href: "/deliveries", label: "My Deliveries", icon: Truck, cap: "deliver_order" },
  { href: "/escalations", label: "Escalations", icon: AlertTriangle, cap: "resolve_escalation" },
  { href: "/conversations", label: "Conversations", icon: MessageSquare, cap: "view_conversations" },
  { href: "/reports", label: "Reports", icon: FileBarChart, cap: "view_reports" },
  { href: "/analytics", label: "Analytics", icon: TrendingUp, cap: "view_analytics" },
  { href: "/printing", label: "Print Queue", icon: Printer, cap: "view_printing" },
  { href: "/zones", label: "Zones", icon: MapPin, cap: "manage_users" },
  { href: "/branches", label: "Branches", icon: Building2, cap: "manage_users" },
  { href: "/billing", label: "Billing & Plan", icon: CreditCard, cap: "view_billing" },
  { href: "/admin", label: "Team & Access", icon: Users, cap: "manage_users" },
  // Stonic's own console; shown only to the emails in PLATFORM_ADMIN_EMAILS
  { href: "/platform", label: "Stonic Console", icon: Landmark, cap: "platform" },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { me } = useMe();
  const visible = nav.filter((n) =>
    n.cap === null || (n.cap === "platform" ? !!me?.is_platform_admin : can(me, n.cap)));

  return (
    <nav className="flex-1 space-y-1 px-3">
      {visible.map(({ href, label, icon: Icon }) => {
        const active = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
              active ? "bg-indigo-50 text-[var(--primary)]" : "text-slate-600 hover:bg-gray-100"
            }`}
          >
            <Icon size={18} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function Sidebar() {
  const router = useRouter();
  const { me } = useMe();
  const [open, setOpen] = useState(false);

  function logout() {
    clearToken();
    router.replace("/login");
  }

  const brand = (
    <div className="text-lg font-bold tracking-tight text-slate-900">
      Salesman<span className="text-[var(--primary)]">.</span>
    </div>
  );

  const userLine = me && (
    <div className="px-6 pb-2 text-xs text-slate-400">
      {me.full_name || me.email} · <span className="capitalize">{me.role}</span>
    </div>
  );

  return (
    <>
      {/* Mobile top bar -- shown below md, replaces the fixed sidebar */}
      <div className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-[var(--border)] bg-white px-4 md:hidden">
        <Link href="/overview" className="text-base font-bold tracking-tight text-slate-900">
          Salesman<span className="text-[var(--primary)]">.</span>
        </Link>
        <button
          onClick={() => setOpen(true)}
          aria-label="Open menu"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-gray-100"
        >
          <Menu size={22} />
        </button>
      </div>

      {/* Desktop sidebar -- fixed column, always visible at md and up */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-[var(--border)] bg-white md:flex">
        <div className="px-6 py-5">{brand}</div>
        {userLine}
        <BranchSwitcher />
        <NavList />
        <button
          onClick={logout}
          className="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-gray-100"
        >
          <LogOut size={18} /> Sign out
        </button>
      </aside>

      {/* Mobile drawer -- slides in below md */}
      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white shadow-xl">
            <div className="flex items-center justify-between px-6 py-5">
              {brand}
              <button
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-gray-100"
              >
                <X size={20} />
              </button>
            </div>
            {userLine}
            <BranchSwitcher onChange={() => setOpen(false)} />
            <NavList onNavigate={() => setOpen(false)} />
            <button
              onClick={() => { setOpen(false); logout(); }}
              className="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-gray-100"
            >
              <LogOut size={18} /> Sign out
            </button>
          </div>
        </div>
      )}
    </>
  );
}