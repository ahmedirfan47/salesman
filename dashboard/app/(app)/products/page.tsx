"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";

type Product = {
  id: string;
  sku: string;
  name_en: string;
  name_ar: string | null;
  category: string | null;
  is_active: boolean;
};

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/products")
      .then(setProducts)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Products</h1>
      <p className="mb-6 text-sm text-slate-500">{products.length} products</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">SKU</th>
              <th className="px-4 py-3 font-medium">Name</th>
              <th className="px-4 py-3 font-medium">Category</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-3 font-mono text-xs">{p.sku}</td>
                <td className="px-4 py-3">{p.name_en}</td>
                <td className="px-4 py-3 text-slate-500">{p.category ?? "—"}</td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${p.is_active ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>
                    {p.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
              </tr>
            ))}
            {products.length === 0 && !error && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No products yet</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}