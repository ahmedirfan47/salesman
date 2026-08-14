"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type Escalation = {
  id: string;
  reason_type: string;
  ai_recommendation: string | null;
  customer_name: string | null;
  status: string;
  created_at: string;
};

export default function EscalationsPage() {
  const [items, setItems] = useState<Escalation[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    api("/orders/escalations/open")
      .then(setItems)
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

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Escalations</h1>
      <p className="mb-6 text-sm text-slate-500">Orders waiting for your decision</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {items.length === 0 && !error && (
        <Card className="p-8 text-center text-slate-400">Nothing needs review right now.</Card>
      )}

      <div className="space-y-3">
        {items.map((e) => (
          <Card key={e.id} className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                    {e.reason_type.replace(/_/g, " ")}
                  </span>
                  {e.customer_name && <span className="text-sm font-medium">{e.customer_name}</span>}
                </div>
                <p className="mt-2 text-sm text-slate-600">{e.ai_recommendation}</p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="outline" disabled={busy === e.id} onClick={() => resolve(e.id, false)}>
                  Reject
                </Button>
                <Button disabled={busy === e.id} onClick={() => resolve(e.id, true)}>
                  Approve
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}