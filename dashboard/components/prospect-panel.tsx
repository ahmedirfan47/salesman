"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sparkles, MessageCircle, MapPin, Phone, User, Trophy, XCircle, Pencil, StickyNote, ExternalLink, X,
} from "lucide-react";

export type Assignee = { id: string; name: string | null };
export type Zone = { id: string; name: string };
type Activity = { id: string; kind: string; body: string | null; actor_name: string | null; created_at: string };
export type Prospect = {
  id: string; kind: "new" | "winback"; source: string;
  status: "new" | "contacted" | "interested" | "won" | "lost";
  name: string; contact_name: string | null; phone: string | null; phone_digits: string | null;
  address: string | null; area: string | null; category: string | null;
  zone_id: string | null; zone_name: string | null; google_maps_uri: string | null;
  insight: string | null; notes: string | null; lost_reason: string | null;
  assigned_to_id: string | null; assigned_to_name: string | null; customer_id: string | null;
  last_contacted_at: string | null; closed_at: string | null; created_at: string;
  priority: "high" | "medium" | "low"; priority_reasons: string[];
};
type Detail = Prospect & { activities: Activity[] };

export const STATUS_LABEL: Record<Prospect["status"], string> = {
  new: "New", contacted: "Contacted", interested: "Interested", won: "Won", lost: "Lost",
};
export const STATUS_TONE: Record<Prospect["status"], string> = {
  new: "bg-slate-100 text-slate-700",
  contacted: "bg-blue-50 text-blue-700",
  interested: "bg-amber-50 text-amber-700",
  won: "bg-emerald-50 text-emerald-700",
  lost: "bg-red-50 text-red-700",
};
const PRIORITY_TONE = { high: "text-emerald-700", medium: "text-amber-700", low: "text-slate-500" };
const ACTIVITY_LABEL: Record<string, string> = {
  created: "Added", note: "Note", contacted: "WhatsApp opened", status: "Status", won: "Won",
};

export function KindBadge({ kind }: { kind: Prospect["kind"] }) {
  return kind === "winback" ? (
    <span className="rounded-full bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">Win-back</span>
  ) : (
    <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-[var(--primary)]">New shop</span>
  );
}

export function when(iso: string | null): string {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  return days < 30 ? `${days} d ago` : new Date(iso).toLocaleDateString();
}

const select = "rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm";

export function ProspectPanel({
  id, zones, assignees, onChanged, onClose,
}: {
  id: string;
  zones: Zone[];
  assignees: Assignee[];
  onChanged: () => void;
  onClose: () => void;
}) {
  const [p, setP] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [message, setMessage] = useState("");
  const [source, setSource] = useState<"ai" | "template" | null>(null);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", contact_name: "", address: "", area: "", zone_id: "" });
  const [winZone, setWinZone] = useState("");
  const [lostReason, setLostReason] = useState("");
  const [showLost, setShowLost] = useState(false);

  function apply(d: Detail) {
    setP(d);
    setForm({
      name: d.name, phone: d.phone ?? "", contact_name: d.contact_name ?? "",
      address: d.address ?? "", area: d.area ?? "", zone_id: d.zone_id ?? "",
    });
    setWinZone(d.zone_id ?? "");
  }

  useEffect(() => {
    setP(null); setMessage(""); setSource(null); setError(""); setEditing(false); setShowLost(false);
    api(`/prospects/${id}`).then(apply).catch((e) => setError(e.message));
  }, [id]);

  async function run(label: string, fn: () => Promise<Detail | void>): Promise<boolean> {
    setBusy(label); setError("");
    try {
      const d = await fn();
      if (d) { apply(d); onChanged(); }
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      return false;
    } finally {
      setBusy("");
    }
  }

  const patch = (body: Record<string, unknown>) =>
    run("save", () => api(`/prospects/${id}`, { method: "PATCH", body: JSON.stringify(body) }));

  async function draft() {
    setBusy("draft"); setError("");
    try {
      const d = await api(`/prospects/${id}/draft`, { method: "POST", body: JSON.stringify({ language }) });
      setMessage(d.message);
      setSource(d.source);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy("");
    }
  }

  function openWhatsApp() {
    if (!p?.phone_digits) return;
    // open synchronously so the browser doesn't block it as a pop-up
    const url = `https://wa.me/${p.phone_digits}${message.trim() ? `?text=${encodeURIComponent(message.trim())}` : ""}`;
    window.open(url, "_blank", "noopener");
    run("contacted", () => api(`/prospects/${id}/contacted`, {
      method: "POST", body: JSON.stringify({ message: message.trim() || null }),
    }));
  }

  if (!p) {
    return (
      <Card className="p-6">
        {error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-sm text-slate-400">Loading…</p>}
      </Card>
    );
  }

  const closed = p.status === "won" || p.status === "lost";

  return (
    <Card className="p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <KindBadge kind={p.kind} />
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[p.status]}`}>{STATUS_LABEL[p.status]}</span>
            <span className={`text-xs font-semibold capitalize ${PRIORITY_TONE[p.priority]}`}>{p.priority} priority</span>
          </div>
          <h2 className="truncate text-lg font-bold">{p.name}</h2>
        </div>
        <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-500 hover:bg-gray-100">
          <X size={18} />
        </button>
      </div>

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      {p.priority_reasons.length > 0 && (
        <ul className="mb-4 space-y-1 rounded-lg bg-gray-50 p-3 text-xs text-slate-600">
          {p.priority_reasons.map((r) => <li key={r}>• {r}</li>)}
        </ul>
      )}

      {/* contact details */}
      {!editing ? (
        <div className="mb-4 space-y-1.5 text-sm">
          <div className="flex items-center gap-2"><Phone size={14} className="text-slate-400" />{p.phone ?? <span className="text-slate-400">No phone number</span>}</div>
          {p.contact_name && <div className="flex items-center gap-2"><User size={14} className="text-slate-400" />{p.contact_name}</div>}
          <div className="flex items-center gap-2">
            <MapPin size={14} className="text-slate-400" />
            {[p.address, p.area, p.zone_name].filter(Boolean).join(" · ") || <span className="text-slate-400">No address</span>}
          </div>
          {p.google_maps_uri && (
            <a href={p.google_maps_uri} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-[var(--primary)] hover:underline">
              View on Google Maps <ExternalLink size={12} />
            </a>
          )}
          {!closed && (
            <div>
              <button onClick={() => setEditing(true)} className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
                <Pencil size={12} /> Edit details
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Shop name" />
          <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="Phone (05…)" />
          <Input value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} placeholder="Contact person" />
          <Input value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} placeholder="Area / district" />
          <Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="Address" className="sm:col-span-2" />
          <select value={form.zone_id} onChange={(e) => setForm({ ...form, zone_id: e.target.value })} className={select}>
            <option value="">No zone</option>
            {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
          </select>
          <div className="flex gap-2">
            <Button disabled={busy !== ""} onClick={async () => {
              const ok = await patch({
                name: form.name, phone: form.phone || null, contact_name: form.contact_name || null,
                address: form.address || null, area: form.area || null, zone_id: form.zone_id || null,
              });
              if (ok) setEditing(false);
            }}>Save</Button>
            <Button variant="outline" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      )}

      {/* status and owner */}
      <div className="mb-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="text-xs font-medium text-slate-500">
          Status
          <select value={p.status} disabled={closed && p.status === "won"} onChange={(e) => {
            if (e.target.value === "lost") { setShowLost(true); return; }
            patch({ status: e.target.value });
          }} className={`${select} mt-1 w-full`}>
            {(["new", "contacted", "interested", "lost"] as const).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            {p.status === "won" && <option value="won">Won</option>}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-500">
          Assigned to
          <select value={p.assigned_to_id ?? ""} onChange={(e) => patch({ assigned_to_id: e.target.value || null })}
            className={`${select} mt-1 w-full`}>
            <option value="">Unassigned</option>
            {assignees.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
      </div>

      {showLost && (
        <div className="mb-5 rounded-lg border border-red-100 bg-red-50 p-3">
          <p className="mb-2 text-xs font-medium text-red-800">Why was it lost? (optional)</p>
          <div className="flex gap-2">
            <Input value={lostReason} onChange={(e) => setLostReason(e.target.value)} placeholder="e.g. Has a fixed supplier" />
            <Button variant="danger" disabled={busy !== ""} onClick={async () => {
              if (await patch({ status: "lost", lost_reason: lostReason || null })) {
                setShowLost(false); setLostReason("");
              }
            }}>Mark lost</Button>
            <Button variant="outline" onClick={() => setShowLost(false)}>Cancel</Button>
          </div>
        </div>
      )}

      {/* WhatsApp message */}
      {!closed && (
        <div className="mb-5 rounded-xl border border-[var(--border)] p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold"><MessageCircle size={16} className="text-emerald-600" /> WhatsApp message</h3>
            <div className="flex rounded-lg border border-[var(--border)] p-0.5 text-xs">
              {(["en", "ar"] as const).map((l) => (
                <button key={l} onClick={() => setLanguage(l)}
                  className={`rounded-md px-2.5 py-1 font-medium ${language === l ? "bg-[var(--primary)] text-white" : "text-slate-600"}`}>
                  {l === "en" ? "English" : "العربية"}
                </button>
              ))}
            </div>
          </div>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            dir={language === "ar" ? "rtl" : "ltr"}
            rows={6}
            placeholder="Draft a message with AI, or write your own."
            className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)] focus:ring-2 focus:ring-indigo-100"
          />
          {source && (
            <p className="mt-1 text-xs text-slate-500">
              {source === "ai"
                ? "AI draft. Every price was checked against today's price list. Review before sending."
                : "Standard message. The AI was unavailable or its draft didn't pass the price check."}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" onClick={draft} disabled={busy !== ""}>
              <Sparkles size={16} /> {busy === "draft" ? "Drafting…" : message ? "Redraft" : "Draft with AI"}
            </Button>
            <Button onClick={openWhatsApp} disabled={!p.phone_digits || busy !== ""} className="bg-emerald-600 hover:bg-emerald-700">
              <MessageCircle size={16} /> Open in WhatsApp
            </Button>
          </div>
          {!p.phone_digits && <p className="mt-2 text-xs text-amber-700">Add a phone number to message this shop.</p>}
        </div>
      )}

      {/* close as won */}
      {!closed && (
        <div className="mb-5 flex flex-wrap items-center gap-2">
          {p.kind === "new" && (
            <select value={winZone} onChange={(e) => setWinZone(e.target.value)} className={select}>
              <option value="">Delivery zone…</option>
              {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          )}
          <Button variant="outline" disabled={busy !== ""} onClick={() => run("won", () => api(`/prospects/${id}/convert`, {
            method: "POST", body: JSON.stringify({ zone_id: winZone || null }),
          }))}>
            <Trophy size={16} className="text-emerald-600" /> {p.kind === "new" ? "Won: add as customer" : "Mark as won back"}
          </Button>
          <Button variant="ghost" onClick={() => setShowLost(true)}><XCircle size={16} className="text-red-500" /> Lost</Button>
        </div>
      )}
      {p.status === "lost" && p.lost_reason && <p className="mb-4 text-sm text-red-700">Lost: {p.lost_reason}</p>}

      {/* notes and timeline */}
      <div>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><StickyNote size={16} className="text-slate-400" /> Notes and history</h3>
        <div className="mb-3 flex gap-2">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note, e.g. call back after Asr" />
          <Button variant="outline" disabled={!note.trim() || busy !== ""} onClick={async () => {
            if (await run("note", () => api(`/prospects/${id}/notes`, { method: "POST", body: JSON.stringify({ text: note }) }))) {
              setNote("");
            }
          }}>Add</Button>
        </div>
        <ol className="space-y-3">
          {p.activities.map((a) => (
            <li key={a.id} className="border-l-2 border-[var(--border)] pl-3">
              <div className="text-xs text-slate-400">
                <span className="font-medium text-slate-600">{ACTIVITY_LABEL[a.kind] ?? a.kind}</span>
                {a.actor_name ? ` · ${a.actor_name}` : ""} · {when(a.created_at)}
              </div>
              {a.body && <p className="mt-0.5 whitespace-pre-wrap text-sm text-slate-700" dir="auto">{a.body}</p>}
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}