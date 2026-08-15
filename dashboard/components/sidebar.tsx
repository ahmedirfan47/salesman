"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard, Package, Tag, ShoppingCart, AlertTriangle,
  FileBarChart, Printer, MessageSquare, Users, LogOut,
} from "lucide-react";
import { clearToken } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";

// each item lists the capability required to see it (null = everyone logged in)
const nav = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard, cap: null },
  { href: "/products", label: "Products", icon: Package, cap: null },
  { href: "/pricing", label: "Pricing", icon: Tag, cap: "manage_pricing" },
  { href: "/orders", label: "Orders", icon: ShoppingCart, cap: "view_orders" },
  { href: "/escalations", label: "Escalations", icon: AlertTriangle, cap: "resolve_escalation" },
  { href: "/conversations", label: "Conversations", icon: MessageSquare, cap: "view_conversations" },
  { href: "/reports", label: "Reports", icon: FileBarChart, cap: "view_reports" },
  { href: "/printing", label: "Print Queue", icon: Printer, cap: "view_printing" },
  { href: "/admin", label: "Team & Access", icon: Users, cap: "manage_users" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { me } = useMe();

  function logout() {
    clearToken();
    router.replace("/login");
  }

  const visible = nav.filter((n) => n.cap === null || can(me, n.cap));

  return (
    <aside className="flex w-60 flex-col border-r border-[var(--border)] bg-white">
      <div className="px-6 py-5 text-lg font-bold tracking-tight">
        Salesman<span className="text-[var(--primary)]">.</span>
      </div>
      {me && (
        <div className="mb-2 px-6 text-xs text-slate-400">
          {me.full_name || me.email} · <span className="capitalize">{me.role}</span>
        </div>
      )}
      <nav className="flex-1 space-y-1 px-3">
        {visible.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link key={href} href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                active ? "bg-indigo-50 text-[var(--primary)]" : "text-slate-600 hover:bg-gray-100"
              }`}>
              <Icon size={18} />
              {label}
            </Link>
          );
        })}
      </nav>
      <button onClick={logout}
        className="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-gray-100">
        <LogOut size={18} />
        Sign out
      </button>
    </aside>
  );
}