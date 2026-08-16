"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Plus, Trash2, ArrowLeft } from "lucide-react";
import Link from "next/link";

type Product = { id: string; sku: string; name_en: string; is_active: boolean };
type Customer = { id: string; name: string; company: string | null; zone_id: string | null };
type Line = { sku: string; quantity: number };

export default function NewOrderPage() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerId, setCustomerId] = useState("");   // saved customer
  const [walkIn, setWalkIn] = useState("");            // free-text name if no saved customer
  const [lines, setLines] = useState<Line[]>([{ sku: "", quantity: 1 }]);
  const [error, setError] = useState("");
  const [result, setResult] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api("/products")
      .then((p: Product[]) => setProducts(p.filter((x) => x.is_active)))
      .catch((e) => setError(e.message));
    // customers may be admin-only; ignore failure (non-admins just type a name)
    api("/customers").then(setCustomers).catch(() => setCustomers([]));
  }, []);

  function updateLine(i: number, patch: Partial<Line>) {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  function addLine() { setLines((prev) => [...prev, { sku: "", quantity: 1 }]); }
  function removeLine(i: number) { setLines((prev) => prev.filter((_, idx) => idx !== i)); }

  const selectedCustomer = customers.find((c) => c.id === customerId);

  async function submit() {
    setError(""); setResult("");
    const items = lines
      .filter((l) => l.sku && l.quantity > 0)
      .map((l) => ({ sku: l.sku, quantity: Number(l.quantity) }));
    if (items.length === 0) {
      setError("Add at least one product with a quantity.");
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = { items };
      if (customerId) body.customer_id = customerId;
      else if (walkIn) body.customer_name = walkIn;

      const order = await api("/orders", { method: "POST", body: JSON.stringify(body) });
      if (order.status === "requires_human_review") {
        setResult(`Order ${order.order_number} created but needs review (not enough stock). Check Escalations.`);
      } else {
        setResult(`Order ${order.order_number} confirmed! Redirecting…`);
        setTimeout(() => router.push("/orders"), 1500);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create order");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <Link href="/orders" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft size={16} /> Back to Orders
      </Link>
      <h1 className="mb-1 text-2xl font-bold">New Order</h1>
      <p className="mb-6 text-sm text-slate-500">Place an order manually (simulates what the AI agent does)</p>

      <Card className="p-6">
        <div className="mb-5">
          <label className="mb-1 block text-sm font-medium">Customer</label>
          {customers.length > 0 ? (
            <>
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm">
                <option value="">— Walk-in / not saved —</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}{c.company ? ` (${c.company})` : ""}</option>
                ))}
              </select>
              {customerId && !selectedCustomer?.zone_id && (
                <p className="mt-1 text-xs text-amber-600">This customer has no zone set — it won't auto-route until you add one in Customers.</p>
              )}
              {!customerId && (
                <Input className="mt-2" placeholder="Walk-in customer name (optional)" value={walkIn} onChange={(e) => setWalkIn(e.target.value)} />
              )}
            </>
          ) : (
            <Input placeholder="Customer name (optional)" value={walkIn} onChange={(e) => setWalkIn(e.target.value)} />
          )}
        </div>

        <label className="mb-2 block text-sm font-medium">Items</label>
        <div className="space-y-3">
          {lines.map((line, i) => (
            <div key={i} className="flex items-center gap-2">
              <select value={line.sku} onChange={(e) => updateLine(i, { sku: e.target.value })}
                className="flex-1 rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--primary)]">
                <option value="">Select a product…</option>
                {products.map((p) => (
                  <option key={p.id} value={p.sku}>{p.sku} — {p.name_en}</option>
                ))}
              </select>
              <Input type="number" min={1} value={line.quantity}
                onChange={(e) => updateLine(i, { quantity: Number(e.target.value) })} className="w-24" />
              {lines.length > 1 && (
                <button onClick={() => removeLine(i)} className="p-2 text-slate-400 hover:text-red-600"><Trash2 size={16} /></button>
              )}
            </div>
          ))}
        </div>

        <button onClick={addLine} className="mt-3 inline-flex items-center gap-1 text-sm text-[var(--primary)] hover:underline">
          <Plus size={16} /> Add another product
        </button>

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
        {result && <p className="mt-4 text-sm text-emerald-700">{result}</p>}

        <div className="mt-6 flex justify-end">
          <Button onClick={submit} disabled={submitting}>{submitting ? "Placing…" : "Place Order"}</Button>
        </div>
      </Card>
    </div>
  );
}