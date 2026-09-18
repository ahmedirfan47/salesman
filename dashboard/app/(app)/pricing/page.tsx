"use client";

import { useEffect, useRef, useState } from "react";
import { api, uploadFile } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Upload, CheckCircle2, FileSpreadsheet } from "lucide-react";
import { TableScroll } from "@/components/table-scroll";

type PriceList = {
  id: string;
  version: number;
  source_filename: string | null;
  status: string;
  activated_at: string | null;
  created_at: string;
};

const statusColor: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700",
  pending: "bg-amber-50 text-amber-700",
  superseded: "bg-gray-100 text-gray-500",
  failed: "bg-red-50 text-red-700",
};

export default function PricingPage() {
  const [lists, setLists] = useState<PriceList[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function load() {
    api("/pricing/price-lists")
      .then(setLists)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const pl = await uploadFile("/pricing/price-lists/upload", file);
      setMsg(`Uploaded "${pl.source_filename}" as version ${pl.version} (draft). Review, then activate.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function activate(id: string) {
    setError("");
    setBusy(true);
    try {
      await api(`/pricing/price-lists/${id}/activate`, { method: "POST" });
      setMsg("Price list activated. Prices and stock are now live.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Activation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Pricing</h1>
      <p className="mb-6 text-sm text-slate-500">Upload your daily price sheet (.xlsx)</p>

      <Card className="mb-6 p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-[var(--primary)]">
            <FileSpreadsheet size={24} />
          </div>
          <div className="flex-1">
            <p className="font-medium">Upload a price sheet</p>
            <p className="text-sm text-slate-500">
              Excel file with columns for SKU, Name, Price, Quantity.
            </p>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx"
            onChange={onUpload}
            className="hidden"
            id="file-upload"
          />
          <Button disabled={busy} onClick={() => fileRef.current?.click()} className="w-full sm:w-auto">
            <Upload size={16} />
            {busy ? "Uploading…" : "Choose file"}
          </Button>
        </div>
        {msg && <p className="mt-4 text-sm text-emerald-700">{msg}</p>}
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </Card>

      <h2 className="mb-3 text-sm font-semibold text-slate-500">VERSION HISTORY</h2>
      <Card className="overflow-hidden">
        <TableScroll>
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Version</th>
                <th className="px-4 py-3 font-medium">File</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Uploaded</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {lists.map((pl) => (
                <tr key={pl.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-3 font-mono">v{pl.version}</td>
                  <td className="px-4 py-3">{pl.source_filename ?? "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${statusColor[pl.status] ?? "bg-gray-100"}`}>
                      {pl.status === "active" && <CheckCircle2 size={12} />}
                      {pl.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {new Date(pl.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {pl.status === "pending" && (
                      <Button disabled={busy} onClick={() => activate(pl.id)}>
                        Activate
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {lists.length === 0 && !error && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No price lists yet</td></tr>
              )}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </div>
  );
}