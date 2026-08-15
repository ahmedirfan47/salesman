"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Package,
  Tag,
  ShoppingCart,
  AlertTriangle,
  FileBarChart,
  Printer,
  MessageSquare,
  LogOut,
} from "lucide-react";
import { clearToken } from "@/lib/api";

const nav = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/products", label: "Products", icon: Package },
  { href: "/pricing", label: "Pricing", icon: Tag },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/escalations", label: "Escalations", icon: AlertTriangle },
  { href: "/conversations", label: "Conversations", icon: MessageSquare },
  { href: "/reports", label: "Reports", icon: FileBarChart },
  { href: "/printing", label: "Print Queue", icon: Printer },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  function logout() {
    clearToken();
    router.replace("/login");
  }

  return (
    <aside className="flex w-60 flex-col border-r border-[var(--border)] bg-white">
      <div className="px-6 py-5 text-lg font-bold tracking-tight">
        Salesman<span className="text-[var(--primary)]">.</span>
      </div>
      <nav className="flex-1 space-y-1 px-3">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                active
                  ? "bg-indigo-50 text-[var(--primary)]"
                  : "text-slate-600 hover:bg-gray-100"
              }`}
            >
              <Icon size={18} />
              {label}
            </Link>
          );
        })}
      </nav>
      <button
        onClick={logout}
        className="m-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-gray-100"
      >
        <LogOut size={18} />
        Sign out
      </button>
    </aside>
  );
}