"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { useBranches } from "@/lib/branches";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { BadgePercent, Calculator, Gift, ShieldAlert, Trash2, UserRound } from "lucide-react";

type Customer = { id: string; name: string; company: string | null };
type Product = { sku: string; name_en: string };
type CustomerPrice = {
  id: string; customer_id: string; customer_name: string; sku: string; product_name: string; branch_id: string | null;
  unit_price: string; min_quantity: number; valid_from: string | null; valid_to: string | null; note: string | null;
};
type Promotion = {
  id: string; name: string; kind: "percent_off" | "fixed_price" | "buy_get"; summary: string; live: boolean; sku: string | null;
  product_name: string | null; branch_id: string | null; customer_id: string | null; customer_name: string | null;
  min_quantity: number; percent_off: string | null; fixed_price: string | null; buy_quantity: number | null;
  free_quantity: number | null; free_sku: string | null; starts_on: string | null; ends_on: string | null; is_active: boolean;
};
type Quote = {
  sku: string; quantity: number; list_price: string; unit_price: string; source: string; promotion: string | null;
  line_total: string; free: { sku: string; name: string; quantity: number; promotion: string }[];
};

const select = "mt-1 w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";
const money = (v: string | number) => Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const KIND_LABEL = { percent_off: "% off", fixed_price: "Deal price", buy_get: "Buy X, get Y free" };

export default function DealsPage() {
  const { me, loading } = useMe();
  const manage = can(me, "manage_pricing");
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    api("/customers").then(setCustomers).catch(() => setCustomers([]));
    api("/products").then(setProducts).catch(() => setProducts([]));
  }, []);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!can(me, "create_order")) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">No access</h1>
      </Card>
    );
  }

  return (
    <div className="max-w-5xl space-y-8">
      <div>
        <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><BadgePercent size={22} /> Deals</h1>
        <p className="text-sm text-slate-500">
          Prices agreed with one customer, promotions and free goods. The AI and every order use them automatically: a customer
          always pays the lowest of the list price, their own price and any deal that applies (deals don&apos;t stack). Free
          goods are added as separate lines and never take stock a paid line needs.
        </p>
      </div>
      <datalist id="deal-skus">{products.map((p) => <option key={p.sku} value={p.sku}>{p.name_en}</option>)}</datalist>
      <PriceCheck customers={customers} />
      <CustomerPrices customers={customers} manage={manage} />
      <Promotions customers={customers} manage={manage} />
    </div>
  );
}

function customerName(c: Customer) {
  return c.company || c.name;
}

// ---------------------------------------------------------------- price check
function PriceCheck({ customers }: { customers: Customer[] }) {
  const [f, setF] = useState({ customer_id: "", sku: "", quantity: "1" });
  const [q, setQ] = useState<Quote | null>(null);
  const [error, setError] = useState("");

  async function check() {
    setError("");
    setQ(null);
    try {
      const params = new URLSearchParams({ sku: f.sku.trim(), quantity: f.quantity || "1" });
      if (f.customer_id) params.set("customer_id", f.customer_id);
      setQ(await api(`/deals/quote?${params}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <Card className="p-5">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><Calculator size={16} /> PRICE CHECK</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <label className="text-xs font-medium text-slate-500">Customer
          <select className={select} value={f.customer_id} onChange={(e) => setF({ ...f, customer_id: e.target.value })}>
            <option value="">Any customer</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{customerName(c)}</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-500">SKU
          <Input className="mt-1" list="deal-skus" value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} />
        </label>
        <label className="text-xs font-medium text-slate-500">Quantity
          <Input className="mt-1" type="number" min={1} value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} />
        </label>
        <div className="flex items-end"><Button disabled={!f.sku.trim()} onClick={check}>Check price</Button></div>
      </div>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {q && (
        <div className="mt-4 rounded-lg bg-gray-50 p-3 text-sm">
          <div>
            <span className="font-semibold">{q.quantity} × {money(q.unit_price)}</span> = <span className="font-semibold">{money(q.line_total)}</span>
            {q.source !== "list" && <span className="ml-2 text-slate-500 line-through">{money(q.list_price)}</span>}
            <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-xs text-slate-600">
              {q.source === "customer" ? "Customer's price" : q.source === "promotion" ? q.promotion : "List price"}
            </span>
          </div>
          {q.free.map((fg) => (
            <div key={fg.sku} className="mt-1 flex items-center gap-1 text-emerald-700">
              <Gift size={14} /> {fg.quantity} × {fg.name} free ({fg.promotion})
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- customer prices
function CustomerPrices({ customers, manage }: { customers: Customer[]; manage: boolean }) {
  const { branches } = useBranches();
  const [rows, setRows] = useState<CustomerPrice[] | null>(null);
  const [filter, setFilter] = useState("");
  const blank = { customer_id: "", sku: "", unit_price: "", min_quantity: "1", branch_id: "", valid_from: "", valid_to: "", note: "" };
  const [f, setF] = useState(blank);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api(`/deals/customer-prices${filter ? `?customer_id=${filter}` : ""}`).then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, [filter]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api("/deals/customer-prices", {
        method: "POST",
        body: JSON.stringify({
          customer_id: f.customer_id, sku: f.sku.trim(), unit_price: f.unit_price, min_quantity: Number(f.min_quantity) || 1,
          branch_id: f.branch_id || null, valid_from: f.valid_from || null, valid_to: f.valid_to || null, note: f.note || null,
        }),
      });
      setF({ ...blank, customer_id: f.customer_id });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await api(`/deals/customer-prices/${id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <section>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-500"><UserRound size={16} /> CUSTOMER PRICES</h2>
        <select className="rounded-lg border border-[var(--border)] bg-white px-3 py-1.5 text-sm" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All customers</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{customerName(c)}</option>)}
        </select>
      </div>
      {manage && (
        <Card className="mb-3 p-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label className="col-span-2 text-xs font-medium text-slate-500">Customer
              <select className={select} value={f.customer_id} onChange={(e) => setF({ ...f, customer_id: e.target.value })}>
                <option value="">Choose…</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{customerName(c)}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-500">SKU
              <Input className="mt-1" list="deal-skus" value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">Price per unit
              <Input className="mt-1" type="number" min={0} step="0.01" value={f.unit_price} onChange={(e) => setF({ ...f, unit_price: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">From quantity
              <Input className="mt-1" type="number" min={1} value={f.min_quantity} onChange={(e) => setF({ ...f, min_quantity: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">Branch
              <select className={select} value={f.branch_id} onChange={(e) => setF({ ...f, branch_id: e.target.value })}>
                <option value="">All branches</option>
                {branches.filter((b) => b.is_active).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-500">Valid from
              <Input className="mt-1" type="date" value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">Valid to
              <Input className="mt-1" type="date" value={f.valid_to} onChange={(e) => setF({ ...f, valid_to: e.target.value })} />
            </label>
          </div>
          <Button className="mt-3" disabled={busy || !f.customer_id || !f.sku.trim() || f.unit_price === ""} onClick={save}>
            Save price
          </Button>
        </Card>
      )}
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Customer</th><th className="px-4 py-3 font-medium">Product</th>
                <th className="px-4 py-3 text-right font-medium">Price</th><th className="px-4 py-3 font-medium">From qty</th>
                <th className="px-4 py-3 font-medium">Valid</th><th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r) => (
                <tr key={r.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-3">{r.customer_name}</td>
                  <td className="px-4 py-3"><div>{r.product_name}</div><div className="font-mono text-xs text-slate-400">{r.sku}</div></td>
                  <td className="px-4 py-3 text-right tabular-nums font-medium">{money(r.unit_price)}</td>
                  <td className="px-4 py-3 tabular-nums">{r.min_quantity}+</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {r.valid_from || r.valid_to ? `${r.valid_from ?? "…"} → ${r.valid_to ?? "…"}` : "Always"}
                    {r.branch_id && <div>{branches.find((b) => b.id === r.branch_id)?.name}</div>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {manage && <button type="button" aria-label="Delete" className="text-slate-400 hover:text-red-600" onClick={() => remove(r.id)}><Trash2 size={16} /></button>}
                  </td>
                </tr>
              ))}
              {rows?.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No customer prices yet.</td></tr>}
              {rows === null && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </section>
  );
}

// ---------------------------------------------------------------- promotions
function Promotions({ customers, manage }: { customers: Customer[]; manage: boolean }) {
  const { branches } = useBranches();
  const [rows, setRows] = useState<Promotion[] | null>(null);
  const blank = {
    kind: "percent_off" as Promotion["kind"], name: "", sku: "", percent_off: "", fixed_price: "", buy_quantity: "", free_quantity: "",
    free_sku: "", min_quantity: "1", customer_id: "", branch_id: "", starts_on: "", ends_on: "",
  };
  const [f, setF] = useState(blank);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api("/deals/promotions").then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  const body = (p: typeof blank | Promotion, active = true) => ({
    kind: p.kind, name: ("name" in p && p.name) || null, sku: (p.sku ?? "").trim(),
    percent_off: p.kind === "percent_off" ? p.percent_off || null : null,
    fixed_price: p.kind === "fixed_price" ? p.fixed_price || null : null,
    buy_quantity: p.kind === "buy_get" ? Number(p.buy_quantity) || null : null,
    free_quantity: p.kind === "buy_get" ? Number(p.free_quantity) || null : null,
    free_sku: p.kind === "buy_get" ? p.free_sku || null : null,
    min_quantity: Number(p.min_quantity) || 1, customer_id: p.customer_id || null, branch_id: p.branch_id || null,
    starts_on: p.starts_on || null, ends_on: p.ends_on || null, is_active: active,
  });

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api("/deals/promotions", { method: "POST", body: JSON.stringify(body(f)) });
      setF(blank);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(p: Promotion) {
    try {
      await api(`/deals/promotions/${p.id}`, { method: "PUT", body: JSON.stringify(body(p, !p.is_active)) });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  async function remove(id: string) {
    try {
      await api(`/deals/promotions/${id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  const ready = f.sku.trim() && (f.kind === "percent_off" ? f.percent_off : f.kind === "fixed_price" ? f.fixed_price : f.buy_quantity && f.free_quantity);

  return (
    <section>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-500"><Gift size={16} /> PROMOTIONS AND FREE GOODS</h2>
      {manage && (
        <Card className="mb-3 p-4">
          <div className="mb-3 flex flex-wrap gap-2">
            {(Object.keys(KIND_LABEL) as Promotion["kind"][]).map((k) => (
              <button key={k} type="button" onClick={() => setF({ ...f, kind: k })}
                className={`rounded-full border px-3 py-1 text-xs font-medium ${f.kind === k ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "border-[var(--border)] bg-white text-slate-600"}`}>
                {KIND_LABEL[k]}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label className="text-xs font-medium text-slate-500">SKU
              <Input className="mt-1" list="deal-skus" value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} />
            </label>
            {f.kind === "percent_off" && (
              <label className="text-xs font-medium text-slate-500">% off
                <Input className="mt-1" type="number" min={0.01} max={99.99} step="0.01" value={f.percent_off} onChange={(e) => setF({ ...f, percent_off: e.target.value })} />
              </label>
            )}
            {f.kind === "fixed_price" && (
              <label className="text-xs font-medium text-slate-500">Deal price per unit
                <Input className="mt-1" type="number" min={0} step="0.01" value={f.fixed_price} onChange={(e) => setF({ ...f, fixed_price: e.target.value })} />
              </label>
            )}
            {f.kind === "buy_get" && (
              <>
                <label className="text-xs font-medium text-slate-500">For every
                  <Input className="mt-1" type="number" min={1} value={f.buy_quantity} onChange={(e) => setF({ ...f, buy_quantity: e.target.value })} />
                </label>
                <label className="text-xs font-medium text-slate-500">Free units
                  <Input className="mt-1" type="number" min={1} value={f.free_quantity} onChange={(e) => setF({ ...f, free_quantity: e.target.value })} />
                </label>
                <label className="text-xs font-medium text-slate-500">Free product (empty = same)
                  <Input className="mt-1" list="deal-skus" value={f.free_sku} onChange={(e) => setF({ ...f, free_sku: e.target.value })} />
                </label>
              </>
            )}
            <label className="text-xs font-medium text-slate-500">From quantity
              <Input className="mt-1" type="number" min={1} value={f.min_quantity} onChange={(e) => setF({ ...f, min_quantity: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">Only for
              <select className={select} value={f.customer_id} onChange={(e) => setF({ ...f, customer_id: e.target.value })}>
                <option value="">Every customer</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{customerName(c)}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-500">Branch
              <select className={select} value={f.branch_id} onChange={(e) => setF({ ...f, branch_id: e.target.value })}>
                <option value="">All branches</option>
                {branches.filter((b) => b.is_active).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-500">Starts
              <Input className="mt-1" type="date" value={f.starts_on} onChange={(e) => setF({ ...f, starts_on: e.target.value })} />
            </label>
            <label className="text-xs font-medium text-slate-500">Ends
              <Input className="mt-1" type="date" value={f.ends_on} onChange={(e) => setF({ ...f, ends_on: e.target.value })} />
            </label>
            <label className="col-span-2 text-xs font-medium text-slate-500">Name (optional)
              <Input className="mt-1" placeholder="Written for you if empty" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            </label>
          </div>
          <Button className="mt-3" disabled={busy || !ready} onClick={save}>Add promotion</Button>
        </Card>
      )}
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {(rows ?? []).map((p) => (
          <Card key={p.id} className={`p-4 ${p.is_active ? "" : "opacity-60"}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{p.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${p.live ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-slate-500"}`}>
                    {p.live ? "Live" : p.is_active ? "Scheduled or ended" : "Off"}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-600">{p.summary}</p>
                <p className="mt-1 text-xs text-slate-400">
                  {p.customer_name ? `Only ${p.customer_name}` : "Every customer"}
                  {p.branch_id ? ` · ${branches.find((b) => b.id === p.branch_id)?.name ?? "one branch"}` : ""}
                  {p.starts_on || p.ends_on ? ` · ${p.starts_on ?? "…"} → ${p.ends_on ?? "…"}` : ""}
                </p>
              </div>
              {manage && (
                <div className="flex shrink-0 items-center gap-2">
                  <Button variant="outline" className="px-2 py-1 text-xs" onClick={() => toggle(p)}>{p.is_active ? "Turn off" : "Turn on"}</Button>
                  <button type="button" aria-label="Delete" className="text-slate-400 hover:text-red-600" onClick={() => remove(p.id)}><Trash2 size={16} /></button>
                </div>
              )}
            </div>
          </Card>
        ))}
        {rows?.length === 0 && <Card className="p-4 text-sm text-slate-400 sm:col-span-2">No promotions yet.</Card>}
      </div>
    </section>
  );
}
