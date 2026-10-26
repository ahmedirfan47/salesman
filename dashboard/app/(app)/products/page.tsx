"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import { useBranches } from "@/lib/branches";

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

export default function ProductsPage() {
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
    </div>
  );
}