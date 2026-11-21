"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Bot, Check, Gift, Languages, Pencil, X } from "lucide-react";
import { REASON, REVIEW_KIND, STATUS, T, money, saveLang, savedLang, type Lang } from "@/lib/operator-i18n";

type Item = { sku: string; product_name: string; quantity: number; unit_price: string; line_total: string; is_free?: boolean };
type Order = {
  id: string; order_number: string; status: string; source?: string; customer_name: string | null; customer_company: string | null;
  total_amount: string; currency: string; created_at: string; items: Item[];
};
type Escalation = {
  id: string; reason_type: string; order_id: string | null; customer_name: string | null; created_at: string;
  context: { order_number?: string; review?: { kind: string; sku?: string; message: string }[];
    lines?: { sku: string; quantity: number; wording: string | null; score: number | null }[] };
};
type Product = { sku: string; name_en: string; name_ar: string | null };

const NEXT: Record<string, { to: string; label: keyof typeof T }> = {
  confirmed: { to: "preparing", label: "startPreparing" },
  preparing: { to: "dispatched", label: "markDispatched" },
};

export default function OperatorPage() {
  const [lang, setLang] = useState<Lang>("ar");
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [products, setProducts] = useState<Record<string, Product>>({});
  const [updated, setUpdated] = useState<Date | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const t = (k: keyof typeof T) => T[k][lang];

  useEffect(() => setLang(savedLang()), []);
  useEffect(() => {
    api("/products").then((rows: Product[]) => setProducts(Object.fromEntries(rows.map((p) => [p.sku, p])))).catch(() => {});
  }, []);

  const load = useCallback(() => {
    Promise.all([api("/orders"), api("/orders/escalations/open")])
      .then(([o, e]) => { setOrders(o); setEscalations(e); setUpdated(new Date()); setError(""); })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, [load]);

  const byId = useMemo(() => Object.fromEntries((orders ?? []).map((o) => [o.id, o])), [orders]);
  const today = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return (orders ?? []).filter((o) => new Date(o.created_at) >= start && o.status !== "requires_human_review")
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [orders]);

  const nameOf = (sku: string, fallback: string) => (lang === "ar" ? products[sku]?.name_ar || fallback : fallback);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError("");
    try { await fn(); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  const resolve = (e: Escalation, approve: boolean) =>
    act(e.id, () => api(`/orders/escalations/${e.id}/resolve`, { method: "POST", body: JSON.stringify({ approve }) }));

  const saveCorrection = (e: Escalation) => act(e.id, async () => {
    const words = new Map((e.context.lines ?? []).map((l) => [l.sku, l.wording]));
    await api(`/orders/escalations/${e.id}/correct`, {
      method: "POST",
      body: JSON.stringify({ items: Object.entries(draft).filter(([, q]) => q > 0).map(([sku, quantity]) => ({ sku, quantity, wording: words.get(sku) ?? null })) }),
    });
    setEditing(null);
  });

  const advance = (o: Order) => {
    const step = NEXT[o.status];
    if (step) act(o.id, () => api(`/orders/${o.id}/transition`, { method: "POST", body: JSON.stringify({ to_status: step.to }) }));
  };

  function toggleLang() {
    const next = lang === "ar" ? "en" : "ar";
    setLang(next);
    saveLang(next);
  }

  return (
    <div dir={lang === "ar" ? "rtl" : "ltr"} lang={lang} className="max-w-6xl"
      style={lang === "ar" ? { fontFamily: "Tahoma, 'Segoe UI', 'Noto Sans Arabic', sans-serif" } : undefined}>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="mb-1 text-2xl font-bold">{t("title")}</h1>
          <p className="text-sm text-slate-500">{t("subtitle")}</p>
        </div>
        <div className="flex items-center gap-3">
          {updated && <span className="text-xs text-slate-400">{t("updated")} {updated.toLocaleTimeString(lang === "ar" ? "ar-SA" : "en-US", { timeStyle: "short" })}</span>}
          <Button variant="outline" onClick={toggleLang}><Languages size={16} /> {t("language")}</Button>
        </div>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {orders === null && !error && <p className="text-slate-400">{t("loading")}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
            {t("toReview")}
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">{escalations.length}</span>
          </h2>
          {escalations.length === 0 && <Card className="p-6 text-center text-slate-400">{t("nothingToReview")}</Card>}
          <div className="space-y-3">
            {escalations.map((e) => {
              const order = e.order_id ? byId[e.order_id] : undefined;
              const ai = new Map((e.context.lines ?? []).map((l) => [l.sku, l]));
              const isEditing = editing === e.id;
              return (
                <Card key={e.id} className="p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                      {REASON[e.reason_type]?.[lang] ?? e.reason_type}
                    </span>
                    <span className="font-semibold">{order?.customer_company || e.customer_name}</span>
                    <span className="font-mono text-xs text-slate-400" dir="ltr">{e.context.order_number}</span>
                  </div>
                  {(e.context.review ?? []).length > 0 && (
                    <ul className="mt-2 space-y-0.5 text-xs text-amber-900">
                      {(e.context.review ?? []).map((r, i) => (
                        <li key={i}>• {REVIEW_KIND[r.kind]?.[lang] ?? r.kind}{r.sku ? ` — ${nameOf(r.sku, r.sku)}` : ""}</li>
                      ))}
                    </ul>
                  )}
                  <ul className="mt-3 space-y-1.5 text-sm">
                    {(order?.items ?? []).map((it) => {
                      const said = ai.get(it.sku);
                      return (
                        <li key={it.sku + String(it.is_free)} className="flex flex-wrap items-center gap-2">
                          {isEditing && !it.is_free ? (
                            <Input type="number" min={0} className="w-20" value={draft[it.sku] ?? it.quantity}
                              onChange={(ev) => setDraft({ ...draft, [it.sku]: Math.max(0, Number(ev.target.value) || 0) })} />
                          ) : (
                            <span className="font-semibold tabular-nums">{it.quantity} ×</span>
                          )}
                          <span>{nameOf(it.sku, it.product_name)}</span>
                          {it.is_free && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"><Gift size={12} /> {t("free")}</span>}
                          {said?.wording && <span className="text-xs text-slate-500">{t("customerSaid")}: «{said.wording}»</span>}
                          {said?.score !== null && said?.score !== undefined && (
                            <span className={`rounded-full px-2 py-0.5 text-xs ${said.score >= 0.85 ? "bg-emerald-50 text-emerald-700" : said.score >= 0.6 ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700"}`}>
                              {Math.round(said.score * 100)}% {t("match")}
                            </span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                  {order && <p className="mt-2 text-sm text-slate-600">{t("total")}: <span className="font-semibold">{money(order.total_amount, order.currency, lang)}</span></p>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {isEditing ? (
                      <>
                        <Button disabled={busy === e.id} onClick={() => saveCorrection(e)}><Check size={16} /> {t("saveApprove")}</Button>
                        <Button variant="outline" onClick={() => setEditing(null)}>{t("cancel")}</Button>
                      </>
                    ) : (
                      <>
                        <Button disabled={busy === e.id} onClick={() => resolve(e, true)}><Check size={16} /> {t("approve")}</Button>
                        {order && e.reason_type === "ai_review" && (
                          <Button variant="outline" disabled={busy === e.id} onClick={() => {
                            setDraft(Object.fromEntries(order.items.filter((i) => !i.is_free).map((i) => [i.sku, i.quantity])));
                            setEditing(e.id);
                          }}><Pencil size={16} /> {t("edit")}</Button>
                        )}
                        <Button variant="outline" disabled={busy === e.id} onClick={() => resolve(e, false)}><X size={16} /> {t("reject")}</Button>
                      </>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        </section>

        <section>
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
            {t("today")}
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">{today.length}</span>
          </h2>
          {orders !== null && today.length === 0 && <Card className="p-6 text-center text-slate-400">{t("noOrders")}</Card>}
          <div className="space-y-2">
            {today.map((o) => {
              const step = NEXT[o.status];
              return (
                <Card key={o.id} className="p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-slate-400" dir="ltr">{o.order_number}</span>
                      <span className="font-semibold">{o.customer_company || o.customer_name || "—"}</span>
                      {o.source === "ai" && <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-[var(--primary)]"><Bot size={12} /> {t("ai")}</span>}
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-600">{STATUS[o.status]?.[lang] ?? o.status}</span>
                    </div>
                    <span className="text-sm font-semibold tabular-nums">{money(o.total_amount, o.currency, lang)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {o.items.map((i) => `${i.quantity} × ${nameOf(i.sku, i.product_name)}${i.is_free ? ` (${t("free")})` : ""}`).join(lang === "ar" ? "، " : ", ")}
                  </p>
                  {step && (
                    <Button variant="outline" className="mt-2 px-3 py-1 text-xs" disabled={busy === o.id} onClick={() => advance(o)}>
                      {t(step.label)}
                    </Button>
                  )}
                </Card>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
