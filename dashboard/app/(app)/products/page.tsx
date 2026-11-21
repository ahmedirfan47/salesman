"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { useBranches } from "@/lib/branches";
import { can, useMe } from "@/lib/use-me";
import { Trash2 } from "lucide-react";

type Row = {
  id: string;
  sku: string;
  name_en: string;
  name_ar: string | null;
  category: string | null;
  is_active: boolean;
  unit_price: number | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  stock: number;
};

function price(r: Row) {
  if (r.unit_price != null) return `${r.currency ?? ""} ${r.unit_price.toLocaleString()}`;
  if (r.price_min != null && r.price_max != null) {
    return `${r.currency ?? ""} ${r.price_min.toLocaleString()}–${r.price_max.toLocaleString()}`;
  }
  return null;
}

const LOW_STOCK = 10;

type Alias = {
  id: string;
  product_id: string;
  sku: string;
  product_name: string;
  alias: string;
  customer_name: string | null;
  source: "manual" | "learned" | "correction";
  hits: number;
};

type Match = { product_id: string; sku: string; name_en: string; score: number; matched_by: string };

type AgentSettings = {
  review_min_confidence: number;
  review_quantity_multiple: number;
  learn_aliases: boolean;
  review_all_ai_orders: boolean;
};

const SOURCE_LABEL: Record<Alias["source"], string> = {
  manual: "Added by staff",
  learned: "Learned from an order",
  correction: "Learned from a correction",
};

export default function ProductsPage() {
  const { me } = useMe();
  const manage = can(me, "manage_products");
  const { current, branches, nameOf } = useBranches();
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    api("/products/catalog")
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  const filtered = rows.filter(
    (r) =>
      r.sku.toLowerCase().includes(q.toLowerCase()) ||
      r.name_en.toLowerCase().includes(q.toLowerCase())
  );

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="mb-1 text-2xl font-bold">Products</h1>
          <p className="text-sm text-slate-500">
            {rows.length} products
            {branches.length > 1 && (current
              ? ` · prices and stock at ${nameOf(current)}`
              : " · stock is the total across branches; a price range means branches charge differently")}
          </p>
        </div>
        <Input
          placeholder="Search SKU or name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="w-full sm:w-64"
        />
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">SKU</th>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium text-right">Price</th>
                <th className="px-4 py-3 font-medium text-right">Stock</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-3 font-mono text-xs">{r.sku}</td>
                  <td className="px-4 py-3">{r.name_en}</td>
                  <td className="px-4 py-3 text-right">
                    {price(r) ?? <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className={r.stock <= LOW_STOCK ? "font-semibold text-red-600" : ""}>
                      {r.stock}
                    </span>
                    {r.stock <= LOW_STOCK && (
                      <span className="ml-2 rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-600">low</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${r.is_active ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>
                      {r.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !error && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                  {rows.length === 0 ? "No products yet — upload a price list" : "No matches"}
                </td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>

      <Vocabulary products={rows} manage={manage} />
      <AiChecks manage={manage} />
    </div>
  );
}

function Vocabulary({ products, manage }: { products: Row[]; manage: boolean }) {
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [error, setError] = useState("");
  const [probe, setProbe] = useState("");
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [productId, setProductId] = useState("");
  const [alias, setAlias] = useState("");

  const load = () => api("/products/aliases").then(setAliases).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function test() {
    if (!probe.trim()) return;
    setError("");
    try { setMatches(await api(`/products/match?q=${encodeURIComponent(probe.trim())}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  async function add() {
    if (!productId || alias.trim().length < 2) return;
    setError("");
    try {
      await api(`/products/${productId}/aliases`, { method: "POST", body: JSON.stringify({ alias: alias.trim() }) });
      setAlias("");
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  async function remove(id: string) {
    setError("");
    try {
      await api(`/products/aliases/${id}`, { method: "DELETE" });
      setAliases((a) => a.filter((x) => x.id !== id));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <Card className="mt-6 p-5">
      <h2 className="mb-1 text-sm font-semibold text-slate-500">WORDS CUSTOMERS USE</h2>
      <p className="mb-4 text-xs text-slate-500">
        The AI matches what customers write or say to your products. It learns new words when a customer confirms an
        order and when your team corrects one. Add nicknames here to teach it directly.
      </p>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <Input placeholder='Try a customer phrase, e.g. "حليب صغير" or "the red box"' value={probe}
          onChange={(e) => setProbe(e.target.value)} onKeyDown={(e) => e.key === "Enter" && test()} />
        <Button variant="outline" className="shrink-0 whitespace-nowrap" onClick={test}>Test match</Button>
      </div>
      {matches && (
        <ul className="mb-4 space-y-1 text-sm">
          {matches.length === 0 && <li className="text-slate-400">No product matches. Add an alias below.</li>}
          {matches.slice(0, 5).map((m) => (
            <li key={m.product_id} className="flex items-center gap-2">
              <span className={`w-12 text-right tabular-nums ${m.score >= 0.85 ? "text-emerald-700" : m.score >= 0.6 ? "text-amber-700" : "text-red-600"}`}>
                {Math.round(m.score * 100)}%
              </span>
              <span>{m.name_en}</span>
              <span className="font-mono text-xs text-slate-400">{m.sku}</span>
              {m.matched_by !== "name" && <span className="text-xs text-slate-400">via {m.matched_by.replace("_", " ")}</span>}
            </li>
          ))}
        </ul>
      )}

      {manage && (
        <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-12">
          <select value={productId} onChange={(e) => setProductId(e.target.value)}
            className="rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm sm:col-span-5">
            <option value="">Choose a product…</option>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name_en} ({p.sku})</option>)}
          </select>
          <Input className="sm:col-span-5" placeholder="What customers call it" value={alias} onChange={(e) => setAlias(e.target.value)} />
          <Button className="sm:col-span-2" onClick={add} disabled={!productId || alias.trim().length < 2}>Add</Button>
        </div>
      )}

      <TableScroll>
        <table className="w-full min-w-[620px] text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr><th className="py-2 font-medium">Customer words</th><th className="font-medium">Product</th>
              <th className="font-medium">For</th><th className="font-medium">Source</th><th className="text-right font-medium">Used</th><th /></tr>
          </thead>
          <tbody>
            {aliases.map((a) => (
              <tr key={a.id} className="border-t border-[var(--border)]">
                <td className="py-2 pr-4"><span dir="auto">{a.alias}</span></td>
                <td className="pr-4">{a.product_name} <span className="font-mono text-xs text-slate-400">{a.sku}</span></td>
                <td className="text-slate-500">{a.customer_name ?? "All customers"}</td>
                <td className="text-slate-500">{SOURCE_LABEL[a.source] ?? a.source}</td>
                <td className="text-right tabular-nums">{a.hits}</td>
                <td className="text-right">
                  {manage && (
                    <button aria-label="Delete alias" className="text-slate-400 hover:text-red-600" onClick={() => remove(a.id)}>
                      <Trash2 size={15} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {aliases.length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-slate-400">No aliases yet. They appear as customers order.</td></tr>
            )}
          </tbody>
        </table>
      </TableScroll>
    </Card>
  );
}

function AiChecks({ manage }: { manage: boolean }) {
  const [s, setS] = useState<AgentSettings | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api("/agent/settings").then(setS).catch(() => setS(null)); }, []);
  if (!s) return null;
  const set = (p: Partial<AgentSettings>) => setS({ ...s, ...p });

  async function save() {
    setMsg("");
    try {
      setS(await api("/agent/settings", { method: "PUT", body: JSON.stringify(s) }));
      setMsg("Saved.");
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <Card className="mt-6 p-5">
      <h2 className="mb-1 text-sm font-semibold text-slate-500">AI ORDER CHECKS</h2>
      <p className="mb-4 text-xs text-slate-500">
        When the AI is unsure, the order waits under Escalations instead of being confirmed.
      </p>
      <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">
            Hold when the product match is below ({Math.round(s.review_min_confidence * 100)}%)
          </span>
          <input type="range" min={0.3} max={0.95} step={0.05} value={s.review_min_confidence} disabled={!manage}
            onChange={(e) => set({ review_min_confidence: Number(e.target.value) })} className="w-full" />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">
            Hold when a quantity is more than this many times the customer&apos;s largest before (0 = off)
          </span>
          <Input type="number" min={0} max={100} value={s.review_quantity_multiple} disabled={!manage}
            onChange={(e) => set({ review_quantity_multiple: Number(e.target.value) })} />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={s.learn_aliases} disabled={!manage} onChange={(e) => set({ learn_aliases: e.target.checked })} />
          Learn customers&apos; words from confirmed and corrected orders
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={s.review_all_ai_orders} disabled={!manage} onChange={(e) => set({ review_all_ai_orders: e.target.checked })} />
          Shadow mode: the team approves every AI order (first week of a pilot)
        </label>
      </div>
      {manage && (
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={save}>Save</Button>
          {msg && <span className="text-sm text-slate-600">{msg}</span>}
        </div>
      )}
    </Card>
  );
}
