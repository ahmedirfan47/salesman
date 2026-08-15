"use client";

import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Printer, FileText } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type PrintJob = {
  id: string;
  status: string;
  payload: { order_number?: string; customer_name?: string; total_amount?: number; currency?: string };
  printed_at: string | null;
  created_at: string;
};

const statusColor: Record<string, string> = {
  queued: "bg-amber-50 text-amber-700",
  printing: "bg-blue-50 text-blue-700",
  done: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-700",
};

export default function PrintingPage() {
  const [jobs, setJobs] = useState<PrintJob[]>([]);
  const [error, setError] = useState("");

  function load() {
    api("/printing/jobs")
      .then(setJobs)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  function viewSlip(id: string) {
    fetch(`${API_BASE}/api/v1/printing/jobs/${id}/slip.pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => r.blob())
      .then((b) => window.open(URL.createObjectURL(b), "_blank"));
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Print Queue</h1>
      <p className="mb-6 text-sm text-slate-500">Order slips waiting to print, and print history</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Order</th>
              <th className="px-4 py-3 font-medium">Customer</th>
              <th className="px-4 py-3 font-medium">Total</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-3 font-mono text-xs">{j.payload.order_number ?? "—"}</td>
                <td className="px-4 py-3">{j.payload.customer_name ?? "—"}</td>
                <td className="px-4 py-3">
                  {j.payload.currency} {j.payload.total_amount?.toLocaleString() ?? ""}
                </td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${statusColor[j.status] ?? "bg-gray-100"}`}>
                    {j.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <Button variant="outline" onClick={() => viewSlip(j.id)}>
                    <FileText size={14} />
                    Slip
                  </Button>
                </td>
              </tr>
            ))}
            {jobs.length === 0 && !error && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-slate-400">
                  <Printer size={24} className="mx-auto mb-2 opacity-40" />
                  No print jobs yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}