"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Pencil, Plus, Trash2 } from "lucide-react";

type ReviewReason = {
  kind: "low_confidence" | "unusual_quantity" | "shadow_mode";
  sku?: string;
  message: string;
};

type AiLine = { sku: string; quantity: number; wording: string | null; score: number | null };

type Escalation = {
  id: string;
  reason_type: string;
  context: { order_number?: string; review?: ReviewReason[]; lines?: AiLine[] };
  ai_recommendation: string | null;
  order_id: string | null;
  customer_name: string | null;
  status: string;
  created_at: string;
};

type OrderItem = { sku: string; product_name: string; quantity: number };
type Product = { sku: string; name_en: string };
type EditLine = { sku: string; quantity: number; wording: string };

const REASON_LABEL: Record<string, string> = {
  insufficient_stock: "Short on stock",
  credit: "Credit check",
  ai_review: "Check the AI's order",
};

function scoreBadge(score: number | null) {
  if (score === null) return null;
  const pct = Math.round(score * 100);
  const tone = score >= 0.85 ? "bg-emerald-50 text-emerald-700" : score >= 0.6 ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700";
  return <span className={`rounded-full px-2 py-0.5 text-xs ${tone}`}>{pct}% match</span>;
}

export default function EscalationsPage() {
  const [items, setItems] = useState<Escalation[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [orderItems, setOrderItems] = useState<Record<string, OrderItem[]>>({});
  const [products, setProducts] = useState<Product[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditLine[]>([]);

  function load() {
    api("/orders/escalations/open")
      .then(async (rows: Escalation[]) => {
        setItems(rows);
        const found: Record<string, OrderItem[]> = {};
        await Promise.all(rows.filter((r) => r.order_id).map(async (r) => {
          try {
            const o = await api(`/orders/${r.order_id}`);
            found[r.id] = o.items;
          } catch { /* the order may be outside this branch view */ }
        }));
        setOrderItems(found);
      })
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function resolve(id: string, approve: boolean) {
    setBusy(id);
    setError("");
    try {
      await api(`/orders/escalations/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ approve }),
      });
      setItems((prev) => prev.filter((e) => e.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  async function startEdit(e: Escalation) {
    if (products.length === 0) {
      api("/products").then(setProducts).catch(() => setProducts([]));
    }
    const words = new Map((e.context.lines ?? []).map((l) => [l.sku, l.wording ?? ""]));
    const lines = (orderItems[e.id] ?? []).map((i) => ({ sku: i.sku, quantity: i.quantity, wording: words.get(i.sku) ?? "" }));
    setDraft(lines.length ? lines : (e.context.lines ?? []).map((l) => ({ sku: l.sku, quantity: l.quantity, wording: l.wording ?? "" })));
    setEditing(e.id);
  }

  async function saveCorrection(id: string) {
    setBusy(id);
    setError("");
    try {
      await api(`/orders/escalations/${id}/correct`, {
        method: "POST",
        body: JSON.stringify({
          items: draft.filter((l) => l.sku.trim()).map((l) => ({
            sku: l.sku.trim(), quantity: l.quantity, wording: l.wording.trim() || null,
          })),
        }),
      });
      setItems((prev) => prev.filter((e) => e.id !== id));
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  const patch = (i: number, p: Partial<EditLine>) => setDraft((d) => d.map((l, j) => (j === i ? { ...l, ...p } : l)));

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Escalations</h1>
      <p className="mb-6 text-sm text-slate-500">
        Orders waiting for your decision. Correct an order and the AI remembers what the customer meant.
      </p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {items.length === 0 && !error && (
        <Card className="p-8 text-center text-slate-400">Nothing needs review right now.</Card>
      )}

      <datalist id="sku-options">
        {products.map((p) => <option key={p.sku} value={p.sku}>{p.name_en}</option>)}
      </datalist>

      <div className="space-y-3">
        {items.map((e) => {
          const lines = orderItems[e.id] ?? [];
          const ai = new Map((e.context.lines ?? []).map((l) => [l.sku, l]));
          const flagged = new Set((e.context.review ?? []).map((r) => r.sku).filter(Boolean));
          return (
            <Card key={e.id} className="p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                      {REASON_LABEL[e.reason_type] ?? e.reason_type.replace(/_/g, " ")}
                    </span>
                    {e.customer_name && <span className="text-sm font-medium">{e.customer_name}</span>}
                    {e.context.order_number && <span className="font-mono text-xs text-slate-400">{e.context.order_number}</span>}
                  </div>
                  <p className="mt-2 text-sm text-slate-600">{e.ai_recommendation}</p>

                  {editing !== e.id && lines.length > 0 && (
                    <ul className="mt-3 space-y-1.5 text-sm">
                      {lines.map((l) => {
                        const said = ai.get(l.sku);
                        return (
                          <li key={l.sku} className={`flex flex-wrap items-center gap-2 rounded-lg px-2 py-1 ${flagged.has(l.sku) ? "bg-amber-50/60" : ""}`}>
                            <span className="tabular-nums font-medium">{l.quantity} ×</span>
                            <span>{l.product_name}</span>
                            <span className="font-mono text-xs text-slate-400">{l.sku}</span>
                            {said?.wording && <span className="text-xs text-slate-500">customer said “{said.wording}”</span>}
                            {said && scoreBadge(said.score)}
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  {editing === e.id && (
                    <div className="mt-3 space-y-2">
                      {draft.map((l, i) => (
                        <div key={i} className="grid grid-cols-12 items-center gap-2">
                          <Input className="col-span-5" list="sku-options" placeholder="SKU" value={l.sku}
                            onChange={(ev) => patch(i, { sku: ev.target.value })} />
                          <Input className="col-span-2" type="number" min={1} value={l.quantity}
                            onChange={(ev) => patch(i, { quantity: Math.max(1, Number(ev.target.value) || 1) })} />
                          <Input className="col-span-4" placeholder="Customer's words (optional)" value={l.wording}
                            onChange={(ev) => patch(i, { wording: ev.target.value })} />
                          <button type="button" aria-label="Remove line" className="col-span-1 flex justify-center text-slate-400 hover:text-red-600"
                            onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>
                            <Trash2 size={16} />
                          </button>
                        </div>
                      ))}
                      <button type="button" className="inline-flex items-center gap-1 text-sm text-[var(--primary)]"
                        onClick={() => setDraft((d) => [...d, { sku: "", quantity: 1, wording: "" }])}>
                        <Plus size={14} /> Add line
                      </button>
                      <p className="text-xs text-slate-500">
                        Keep the customer&apos;s words on a line and the AI will understand them next time.
                      </p>
                    </div>
                  )}
                </div>

                <div className="flex shrink-0 flex-wrap gap-2">
                  {editing === e.id ? (
                    <>
                      <Button variant="outline" disabled={busy === e.id} onClick={() => setEditing(null)}>Cancel</Button>
                      <Button disabled={busy === e.id || draft.every((l) => !l.sku.trim())} onClick={() => saveCorrection(e.id)}>
                        Save and approve
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant="outline" className="flex-1 sm:flex-none" disabled={busy === e.id} onClick={() => resolve(e.id, false)}>
                        Reject
                      </Button>
                      {e.order_id && (
                        <Button variant="outline" className="flex-1 sm:flex-none" disabled={busy === e.id} onClick={() => startEdit(e)}>
                          <Pencil size={14} /> Correct
                        </Button>
                      )}
                      <Button className="flex-1 sm:flex-none" disabled={busy === e.id} onClick={() => resolve(e.id, true)}>
                        Approve
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
