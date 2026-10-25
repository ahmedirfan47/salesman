"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, uploadFile } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableScroll } from "@/components/table-scroll";
import {
  Assignee, KindBadge, Prospect, ProspectPanel, STATUS_LABEL, STATUS_TONE, Zone, when,
} from "@/components/prospect-panel";
import {
  ShieldAlert, Target, RefreshCw, Search, MapPinned, Upload, UserPlus, Star, ExternalLink, Info,
} from "lucide-react";

type Summary = {
  counts: Record<string, number>;
  open_new: number;
  open_winback: number;
  google_search_enabled: boolean;
  assignees: Assignee[];
};
type Place = {
  place_id: string; name: string; address: string | null; phone: string | null; phone_display: string | null;
  maps_uri: string | null; rating: number | null; rating_count: number | null; temporarily_closed: boolean;
  already_prospect: boolean; already_customer: boolean;
};
type ImportResult = { created: number; skipped: { row: number; name: string | null; reason: string }[] };
type Tab = "pipeline" | "google" | "add";

const select = "rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";
const PRIORITY_DOT = { high: "bg-emerald-500", medium: "bg-amber-400", low: "bg-slate-300" };

export default function ProspectsPage() {
  const { me, loading } = useMe();
  const allowed = can(me, "manage_prospects");

  const [tab, setTab] = useState<Tab>("pipeline");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [rows, setRows] = useState<Prospect[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [kind, setKind] = useState<"" | "new" | "winback">("");
  const [status, setStatus] = useState("open");
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const loadList = useCallback(async () => {
    const params = new URLSearchParams();
    if (kind) params.set("kind", kind);
    if (status) params.set("status", status);
    if (mine) params.set("mine", "true");
    if (q.trim()) params.set("q", q.trim());
    try {
      setRows(await api(`/prospects?${params.toString()}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [kind, status, mine, q]);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await api("/prospects/summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    if (!allowed) return;
    loadSummary();
    api("/zones").then(setZones).catch(() => setZones([]));
  }, [allowed, loadSummary]);

  useEffect(() => {
    if (!allowed) return;
    const t = setTimeout(loadList, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [allowed, loadList, q]);

  const refreshAll = useCallback(() => { loadList(); loadSummary(); }, [loadList, loadSummary]);

  // below the xl breakpoint the panel sits under the list, so bring it into view
  useEffect(() => {
    if (selected && window.matchMedia("(max-width: 1279px)").matches) {
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selected]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!allowed) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Sales team only</h1>
        <p className="mt-2 text-sm text-slate-500">Prospecting is available to owners, admins and salesmen.</p>
      </Card>
    );
  }

  async function refreshWinbacks() {
    setBusy(true); setError(""); setMsg("");
    try {
      const r = await api("/prospects/winback/refresh", { method: "POST" });
      setMsg(r.created || r.closed
        ? `${r.created} customer${r.created === 1 ? "" : "s"} added for win-back${r.closed ? `, ${r.closed} closed as won (they ordered again)` : ""}.`
        : "No new customers have gone quiet.");
      setKind("winback");
      refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const stats = [
    { label: "New shops in pipeline", value: summary?.open_new ?? 0 },
    { label: "Win-backs open", value: summary?.open_winback ?? 0 },
    { label: "Interested", value: summary?.counts.interested ?? 0 },
    { label: "Won", value: summary?.counts.won ?? 0 },
  ];

  return (
    <div>
      <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Target size={22} className="text-[var(--primary)]" /> Prospects</h1>
      <p className="mb-6 text-sm text-slate-500">Find new shops, win back quiet customers, and reach them on WhatsApp with AI-drafted messages.</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="p-4">
            <div className="text-xs font-medium text-slate-500">{s.label}</div>
            <div className="mt-1 text-2xl font-bold">{s.value}</div>
          </Card>
        ))}
      </div>

      <div className="mb-5 flex flex-wrap gap-1 rounded-xl border border-[var(--border)] bg-white p-1 sm:inline-flex">
        {([
          ["pipeline", "Pipeline", Target],
          ["google", "Find on Google Maps", MapPinned],
          ["add", "Add or import", Upload],
        ] as const).map(([key, label, Icon]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${tab === key ? "bg-indigo-50 text-[var(--primary)]" : "text-slate-600 hover:bg-gray-50"}`}>
            <Icon size={16} /> {label}
          </button>
        ))}
      </div>

      {tab === "pipeline" && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg border border-[var(--border)] bg-white p-0.5 text-sm">
              {([["", "All"], ["new", "New shops"], ["winback", "Win-back"]] as const).map(([k, label]) => (
                <button key={k} onClick={() => setKind(k)}
                  className={`rounded-md px-3 py-1 font-medium ${kind === k ? "bg-[var(--primary)] text-white" : "text-slate-600"}`}>{label}</button>
              ))}
            </div>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={select}>
              <option value="open">Open</option>
              {(["new", "contacted", "interested", "won", "lost"] as const).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
              <option value="">All statuses</option>
            </select>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only mine
            </label>
            <div className="relative min-w-[180px] flex-1">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, phone, area" className="pl-9" />
            </div>
            <Button variant="outline" onClick={refreshWinbacks} disabled={busy}>
              <RefreshCw size={16} className={busy ? "animate-spin" : ""} /> Find quiet customers
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
            <Card className={`overflow-hidden ${selected ? "xl:col-span-3" : "xl:col-span-5"}`}>
              <TableScroll>
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="border-b border-[var(--border)] bg-gray-50 text-left text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">Shop</th>
                      <th className="px-4 py-3 font-medium">Phone</th>
                      <th className="px-4 py-3 font-medium">Area</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Owner</th>
                      <th className="px-4 py-3 font-medium">Last contact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} onClick={() => setSelected(r.id)}
                        className={`cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-gray-50 ${selected === r.id ? "bg-indigo-50/60" : ""}`}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span title={`${r.priority} priority`} className={`h-2 w-2 shrink-0 rounded-full ${PRIORITY_DOT[r.priority]}`} />
                            <span className="font-medium" dir="auto">{r.name}</span>
                          </div>
                          <div className="mt-1 pl-4"><KindBadge kind={r.kind} /></div>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{r.phone ?? "—"}</td>
                        <td className="px-4 py-3 text-slate-600">{r.zone_name ?? r.area ?? "—"}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[r.status]}`}>{STATUS_LABEL[r.status]}</span>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{r.assigned_to_name ?? "—"}</td>
                        <td className="px-4 py-3 text-slate-500">{when(r.last_contacted_at)}</td>
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-10 text-center text-slate-400">
                          No prospects here yet. Use <b>Find quiet customers</b>, search Google Maps, or import a list.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </TableScroll>
            </Card>
            {selected && (
              <div ref={panelRef} className="scroll-mt-16 xl:col-span-2">
                <ProspectPanel id={selected} zones={zones} assignees={summary?.assignees ?? []}
                  onChanged={refreshAll} onClose={() => setSelected(null)} />
              </div>
            )}
          </div>
        </>
      )}

      {tab === "google" && (
        <GoogleSearch enabled={summary?.google_search_enabled ?? false} zones={zones}
          onAdded={(id) => { refreshAll(); setSelected(id); }} />
      )}

      {tab === "add" && (
        <AddOrImport zones={zones} onDone={(id) => { refreshAll(); if (id) { setSelected(id); setTab("pipeline"); } }} />
      )}
    </div>
  );
}

function GoogleSearch({ enabled, zones, onAdded }: { enabled: boolean; zones: Zone[]; onAdded: (id: string) => void }) {
  const [what, setWhat] = useState("grocery store");
  const [where, setWhere] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [zoneId, setZoneId] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);

  if (!enabled) {
    return (
      <Card className="flex items-start gap-3 p-6">
        <Info size={18} className="mt-0.5 shrink-0 text-[var(--primary)]" />
        <div className="text-sm text-slate-700">
          <p className="font-semibold">Google Maps search is switched off</p>
          <p className="mt-1">
            To search for shops by area, add a Google Maps Platform API key with the Places API (New) enabled
            to the server as <code className="rounded bg-gray-100 px-1">GOOGLE_MAPS_API_KEY</code>. Each search is a billed Google request.
            You can still add shops by hand or import a list.
          </p>
        </div>
      </Card>
    );
  }

  const query = `${what.trim()}${where.trim() ? ` in ${where.trim()}` : ""}`;

  async function search(token?: string) {
    if (what.trim().length < 2) return;
    setBusy(true); setError("");
    try {
      const params = new URLSearchParams({ q: query, language });
      if (token) params.set("page_token", token);
      const r = await api(`/prospects/places/search?${params.toString()}`);
      setResults(token ? [...results, ...r.results] : r.results);
      setNext(r.next_page_token);
      setSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  async function add(p: Place) {
    setError("");
    try {
      const created = await api("/prospects/places", {
        method: "POST",
        body: JSON.stringify({
          place_id: p.place_id, name: p.name, address: p.address, phone: p.phone,
          maps_uri: p.maps_uri, zone_id: zoneId || null, area: where.trim() || null,
        }),
      });
      setResults(results.map((r) => (r.place_id === p.place_id ? { ...r, already_prospect: true } : r)));
      onAdded(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <div>
      <Card className="mb-4 p-5">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
          <Input value={what} onChange={(e) => setWhat(e.target.value)} placeholder="What: grocery store, minimarket, restaurant…" />
          <Input value={where} onChange={(e) => setWhere(e.target.value)} list="prospect-zones" placeholder="Where: Al Olaya, Riyadh" />
          <datalist id="prospect-zones">{zones.map((z) => <option key={z.id} value={z.name} />)}</datalist>
          <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "ar")} className={select}>
            <option value="en">English results</option>
            <option value="ar">نتائج بالعربية</option>
          </select>
          <Button onClick={() => search()} disabled={busy || what.trim().length < 2}>
            <Search size={16} /> {busy ? "Searching…" : "Search"}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-600">
          Add to zone:
          <select value={zoneId} onChange={(e) => setZoneId(e.target.value)} className={select}>
            <option value="">No zone</option>
            {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
          </select>
        </div>
      </Card>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {searched && results.length === 0 && !busy && (
        <p className="py-8 text-center text-sm text-slate-400">No places found. Try a different area or wording.</p>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {results.map((p) => (
          <Card key={p.place_id} className="flex flex-col p-4">
            <div className="mb-1 font-semibold" dir="auto">{p.name}</div>
            {p.address && <div className="mb-1 text-xs text-slate-500" dir="auto">{p.address}</div>}
            <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-slate-600">
              <span>{p.phone_display ?? "No phone listed"}</span>
              {p.rating != null && (
                <span className="flex items-center gap-1"><Star size={12} className="fill-amber-400 text-amber-400" />{p.rating.toFixed(1)} ({p.rating_count ?? 0})</span>
              )}
              {p.temporarily_closed && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">Temporarily closed</span>}
            </div>
            <div className="mt-auto flex items-center justify-between gap-2 pt-2">
              {p.maps_uri ? (
                <a href={p.maps_uri} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-[var(--primary)] hover:underline">
                  Google Maps <ExternalLink size={12} />
                </a>
              ) : <span />}
              {p.already_customer ? (
                <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">Already a customer</span>
              ) : p.already_prospect ? (
                <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-slate-600">In your prospects</span>
              ) : (
                <Button variant="outline" className="px-3 py-1.5" onClick={() => add(p)}>
                  <UserPlus size={14} /> Add
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>

      {results.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-slate-400">Results from Google Maps</span>
          {next && <Button variant="outline" disabled={busy} onClick={() => search(next)}>Load more</Button>}
        </div>
      )}
    </div>
  );
}

function AddOrImport({ zones, onDone }: { zones: Zone[]; onDone: (id?: string) => void }) {
  const empty = { name: "", phone: "", contact_name: "", address: "", area: "", category: "", zone_id: "", notes: "" };
  const [form, setForm] = useState(empty);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function addOne() {
    setBusy(true); setError("");
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
      const created = await api("/prospects", { method: "POST", body: JSON.stringify(body) });
      setForm(empty);
      onDone(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function importFile() {
    if (!file) return;
    setBusy(true); setError(""); setResult(null);
    try {
      setResult(await uploadFile("/prospects/import", file));
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="p-6">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-500"><UserPlus size={16} /> ADD A SHOP</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input placeholder="Shop name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input placeholder="Phone / WhatsApp (05…)" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <Input placeholder="Contact person" value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
          <Input placeholder="Type, e.g. Grocery" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <Input placeholder="Area / district" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} />
          <select value={form.zone_id} onChange={(e) => setForm({ ...form, zone_id: e.target.value })} className={select}>
            <option value="">No zone</option>
            {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
          </select>
          <Input placeholder="Address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="sm:col-span-2" />
          <Input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="sm:col-span-2" />
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={addOne} disabled={busy || !form.name.trim()}>{busy ? "Saving…" : "Add prospect"}</Button>
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-500"><Upload size={16} /> IMPORT A LIST</h2>
        <p className="mb-4 text-sm text-slate-600">
          Upload an Excel (.xlsx) or CSV file. Only a <b>Name</b> column is required. Also read: Phone or WhatsApp,
          Contact, Address, Area or City, Zone, Type, Notes. Arabic headers work too, such as اسم المحل and الجوال.
          Shops that are already customers or prospects are skipped.
        </p>
        <input type="file" accept=".xlsx,.csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }}
          className="mb-4 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-[var(--primary)]" />
        <Button onClick={importFile} disabled={busy || !file}>{busy ? "Importing…" : "Import"}</Button>

        {result && (
          <div className="mt-4 text-sm">
            <p className="font-medium text-emerald-700">{result.created} prospect{result.created === 1 ? "" : "s"} imported.</p>
            {result.skipped.length > 0 && (
              <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-[var(--border)]">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-left text-slate-500">
                    <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Shop</th><th className="px-3 py-2">Skipped because</th></tr>
                  </thead>
                  <tbody>
                    {result.skipped.map((s) => (
                      <tr key={`${s.row}-${s.reason}`} className="border-t border-[var(--border)]">
                        <td className="px-3 py-1.5">{s.row}</td>
                        <td className="px-3 py-1.5" dir="auto">{s.name ?? "—"}</td>
                        <td className="px-3 py-1.5 text-slate-600">{s.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {error && <p className="mt-3 whitespace-pre-wrap text-sm text-red-600">{error}</p>}
      </Card>
    </div>
  );
}