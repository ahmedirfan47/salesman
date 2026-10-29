"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ago, num, type Overview } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { TableScroll } from "@/components/table-scroll";
import { Building2, LogIn, MessageSquare, ShoppingCart, Store, Users, Wifi } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const PERIODS = [7, 30, 90] as const;
const WEB = "#4f46e5";
const MOBILE = "#10b981";
const AMBER = "#f59e0b";

function shortDay(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
}

export default function ConsoleOverview() {
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api(`/platform/overview?days=${days}`).then(setData).catch((e) => setError(e.message));
  }, [days]);

  const series = (data?.series ?? []).map((p) => ({ ...p, label: shortDay(p.day) }));

  return (
    <div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-500">
          {data ? <>Usage across all businesses, {shortDay(data.start)} to {shortDay(data.end)} (UTC).</> : "Usage across all businesses."}
        </p>
        <div className="flex gap-1 rounded-lg border border-[var(--border)] bg-white p-1">
          {PERIODS.map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`rounded-md px-3 py-1 text-xs font-medium ${days === d ? "bg-[var(--primary)] text-white" : "text-slate-600 hover:bg-gray-100"}`}>
              {d} days
            </button>
          ))}
        </div>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {!data && !error && <p className="text-slate-400">Loading…</p>}

      {data && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat icon={Wifi} label="Online now" value={num(data.totals.online_now)} hint="Active in the last 10 minutes" />
            <Stat icon={Users} label="Active people" value={num(data.period.active_people)}
              hint={`${num(data.period.web_people)} on the web · ${num(data.period.mobile_people)} on the app`} />
            <Stat icon={ShoppingCart} label="Orders" value={num(data.period.orders)}
              hint={data.period.order_value.map((v) => `${v.currency} ${Number(v.amount).toLocaleString(undefined, { maximumFractionDigits: 0 })}`).join(" · ") || "No sales yet"} />
            <Stat icon={MessageSquare} label="WhatsApp messages" value={num(data.period.messages_in + data.period.messages_out)}
              hint={`${num(data.period.messages_in)} in · ${num(data.period.messages_out)} out`} />
            <Stat icon={Building2} label="Businesses" value={num(data.totals.businesses)}
              hint={`${num(data.period.new_businesses)} new${data.totals.businesses_suspended ? ` · ${data.totals.businesses_suspended} suspended` : ""}`} />
            <Stat icon={Users} label="People" value={num(data.totals.people)} hint={`${num(data.period.new_people)} added in this period`} />
            <Stat icon={LogIn} label="Sign-ins" value={num(data.period.sign_ins)}
              hint={data.period.failed_sign_ins ? `${num(data.period.failed_sign_ins)} failed attempts` : "No failed attempts"}
              warn={data.period.failed_sign_ins > 0} />
            <Stat icon={Store} label="Branches" value={num(data.totals.branches)}
              hint={`${num(data.totals.customers)} customers · ${num(data.totals.products)} products`} />
          </div>

          <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartCard title="ACTIVE PEOPLE PER DAY">
              <BarChart data={series}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={16} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="web" name="Web" stackId="a" fill={WEB} />
                <Bar dataKey="mobile" name="App" stackId="a" fill={MOBILE} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ChartCard>
            <ChartCard title="ORDERS AND SIGN-INS PER DAY">
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={16} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="orders" name="Orders" stroke={WEB} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="sign_ins" name="Sign-ins" stroke={AMBER} strokeWidth={2} dot={false} />
              </LineChart>
            </ChartCard>
            <ChartCard title="WHATSAPP MESSAGES PER DAY">
              <BarChart data={series}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={16} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
                <Tooltip />
                <Bar dataKey="messages" name="Messages" fill={MOBILE} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ChartCard>
            <Card className="p-5">
              <h3 className="mb-3 text-sm font-semibold text-slate-500">MOST ACTIVE BUSINESSES</h3>
              {data.top_businesses.length === 0 ? (
                <p className="py-12 text-center text-sm text-slate-400">No activity in this period</p>
              ) : (
                <TableScroll>
                  <table className="w-full min-w-[420px] text-sm">
                    <thead className="text-left text-xs text-slate-500">
                      <tr>
                        <th className="py-2 pr-3 font-medium">Business</th>
                        <th className="py-2 pr-3 text-right font-medium">Orders</th>
                        <th className="py-2 pr-3 text-right font-medium">Active people</th>
                        <th className="py-2 font-medium">Last active</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_businesses.map((b) => (
                        <tr key={b.id} className="border-t border-[var(--border)]">
                          <td className="py-2 pr-3">
                            <Link href={`/platform/businesses?id=${b.id}`} className="font-medium hover:text-[var(--primary)]">{b.name}</Link>
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums">{num(b.orders)}</td>
                          <td className="py-2 pr-3 text-right tabular-nums">{num(b.active_people)}</td>
                          <td className="whitespace-nowrap py-2 text-slate-500">{ago(b.last_active_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value, hint, warn }: {
  icon: React.ComponentType<{ size?: number; className?: string }>; label: string; value: string; hint: string; warn?: boolean;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-400">
        <Icon size={14} /> {label}
      </div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
      <div className={`mt-0.5 text-xs ${warn ? "text-amber-700" : "text-slate-500"}`}>{hint}</div>
    </Card>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactElement }) {
  return (
    <Card className="p-5">
      <h3 className="mb-4 text-sm font-semibold text-slate-500">{title}</h3>
      <ResponsiveContainer width="100%" height={240}>{children}</ResponsiveContainer>
    </Card>
  );
}