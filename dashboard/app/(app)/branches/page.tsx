"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/use-me";
import { Branch, useBranches } from "@/lib/branches";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Building2, Plus, ShieldAlert, MessageCircle, Star, Copy, Check } from "lucide-react";

type Setup = { template_category: string; template_body_en: string; template_body_ar: string; webhook_path: string };
type Form = {
  name: string; city: string; address: string;
  whatsapp_phone_number_id: string; whatsapp_display_number: string; whatsapp_access_token: string;
  whatsapp_update_template: string; order_updates_enabled: boolean;
};

const EMPTY: Form = {
  name: "", city: "", address: "", whatsapp_phone_number_id: "", whatsapp_display_number: "",
  whatsapp_access_token: "", whatsapp_update_template: "", order_updates_enabled: true,
};

function toForm(b: Branch): Form {
  return {
    name: b.name, city: b.city ?? "", address: b.address ?? "",
    whatsapp_phone_number_id: b.whatsapp_phone_number_id ?? "", whatsapp_display_number: b.whatsapp_display_number ?? "",
    whatsapp_access_token: "", whatsapp_update_template: b.whatsapp_update_template ?? "",
    order_updates_enabled: b.order_updates_enabled,
  };
}

export default function BranchesPage() {
  const { me, loading } = useMe();
  const { branches, reload } = useBranches();
  const [editing, setEditing] = useState<string | null>(null); // branch id, "new", or null
  const [form, setForm] = useState<Form>(EMPTY);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const allowed = can(me, "manage_users");

  useEffect(() => {
    if (allowed) api("/branches/whatsapp-setup").then(setSetup).catch(() => setSetup(null));
  }, [allowed]);

  if (loading) return <p className="text-slate-400">Loading…</p>;
  if (!allowed) {
    return (
      <Card className="mx-auto max-w-md p-8 text-center">
        <ShieldAlert className="mx-auto mb-3 text-amber-500" size={32} />
        <h1 className="text-lg font-bold">Admins only</h1>
        <p className="mt-2 text-sm text-slate-500">Managing branches is an admin task.</p>
      </Card>
    );
  }

  function open(id: string | null) {
    setError(""); setMsg("");
    setEditing(id);
    const b = branches.find((x) => x.id === id);
    setForm(b ? toForm(b) : EMPTY);
  }

  async function save() {
    setBusy(true); setError(""); setMsg("");
    const body: Record<string, unknown> = { ...form };
    if (!form.whatsapp_access_token) delete body.whatsapp_access_token; // keep the saved token
    try {
      if (editing === "new") {
        await api("/branches", { method: "POST", body: JSON.stringify(body) });
        setMsg(`Added ${form.name}.`);
      } else {
        await api(`/branches/${editing}`, { method: "PATCH", body: JSON.stringify(body) });
        setMsg(`Saved ${form.name}.`);
      }
      setEditing(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function patch(b: Branch, body: Record<string, unknown>, done: string) {
    setError(""); setMsg("");
    try {
      await api(`/branches/${b.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setMsg(done);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  async function disconnect(b: Branch) {
    await patch(b, { whatsapp_phone_number_id: "", whatsapp_access_token: "" }, `${b.name} is no longer connected to WhatsApp.`);
    setForm((f) => ({ ...f, whatsapp_phone_number_id: "" }));
  }

  const current = branches.find((b) => b.id === editing);

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Building2 size={22} className="text-[var(--primary)]" /> Branches</h1>
          <p className="text-sm text-slate-500">Each branch has its own prices, stock, zones, staff and WhatsApp number.</p>
        </div>
        <Button onClick={() => open("new")}><Plus size={16} /> Add branch</Button>
      </div>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {msg && <p className="mb-4 text-sm text-emerald-700">{msg}</p>}

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {branches.map((b) => (
          <Card key={b.id} className={`p-5 ${b.is_active ? "" : "opacity-60"}`}>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold">{b.name}</h2>
                  {b.is_default && <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700"><Star size={11} /> Default</span>}
                  {!b.is_active && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-slate-500">Inactive</span>}
                </div>
                <p className="text-sm text-slate-500">{[b.city, b.address].filter(Boolean).join(" · ") || "No address"}</p>
              </div>
              <Button variant="outline" onClick={() => open(b.id)}>Edit</Button>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <MessageCircle size={16} className={b.whatsapp_connected ? "text-emerald-600" : "text-slate-300"} />
              {b.whatsapp_connected
                ? <span>WhatsApp connected{b.whatsapp_display_number ? `: ${b.whatsapp_display_number}` : ""}</span>
                : <span className="text-slate-500">WhatsApp not connected</span>}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Order updates to customers: {b.order_updates_enabled ? "on" : "off"}
              {b.order_updates_enabled && !b.whatsapp_update_template && " (only within 24 hours of the customer's last message; no template set)"}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {!b.is_default && b.is_active && (
                <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => patch(b, { is_default: true }, `${b.name} is now the default branch.`)}>
                  Make default
                </Button>
              )}
              {!b.is_default && (
                <Button variant="ghost" className="px-2 py-1 text-xs"
                  onClick={() => patch(b, { is_active: !b.is_active }, `${b.name} ${b.is_active ? "deactivated" : "reactivated"}.`)}>
                  {b.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>

      {editing && (
        <Card className="mb-6 p-6">
          <h2 className="mb-4 text-sm font-semibold text-slate-500">{editing === "new" ? "NEW BRANCH" : `EDIT ${current?.name.toUpperCase() ?? ""}`}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Input placeholder="Branch name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Input placeholder="City" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
            <Input placeholder="Address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </div>

          <h3 className="mb-2 mt-6 flex items-center gap-2 text-sm font-semibold"><MessageCircle size={16} className="text-emerald-600" /> WhatsApp number</h3>
          <p className="mb-3 text-xs text-slate-500">
            From Meta: WhatsApp Manager → your number → Phone number ID, and a permanent access token from a system user.
            Messages to this number are answered with this branch&apos;s prices and stock.
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Input placeholder="Phone number ID" value={form.whatsapp_phone_number_id} onChange={(e) => setForm({ ...form, whatsapp_phone_number_id: e.target.value })} />
            <Input placeholder="Number shown to customers, e.g. +966 50…" value={form.whatsapp_display_number} onChange={(e) => setForm({ ...form, whatsapp_display_number: e.target.value })} />
            <Input type="password" autoComplete="new-password"
              placeholder={current?.whatsapp_connected ? "Access token saved (enter to replace)" : "Access token"}
              value={form.whatsapp_access_token} onChange={(e) => setForm({ ...form, whatsapp_access_token: e.target.value })} />
          </div>

          <h3 className="mb-2 mt-6 text-sm font-semibold">Order updates to customers</h3>
          <label className="mb-3 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.order_updates_enabled} onChange={(e) => setForm({ ...form, order_updates_enabled: e.target.checked })} />
            Message customers when their order is dispatched, delivered, cancelled, approved or rejected
          </label>
          <Input placeholder="Approved template name (for updates after 24 hours), e.g. order_update"
            value={form.whatsapp_update_template} onChange={(e) => setForm({ ...form, whatsapp_update_template: e.target.value })} />
          {setup && <TemplateHelp setup={setup} />}

          <div className="mt-6 flex flex-wrap justify-end gap-2">
            {current?.whatsapp_connected && (
              <Button variant="ghost" className="mr-auto text-red-600" onClick={() => disconnect(current)}>Disconnect WhatsApp</Button>
            )}
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={save} disabled={busy || !form.name.trim()}>{busy ? "Saving…" : "Save branch"}</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function TemplateHelp({ setup }: { setup: Setup }) {
  return (
    <div className="mt-3 rounded-lg bg-gray-50 p-4 text-xs text-slate-600">
      <p className="mb-2">
        WhatsApp only allows free messages within 24 hours of the customer&apos;s last message. For later updates, create a
        template in WhatsApp Manager (category <b>{setup.template_category}</b>) in English (<code>en</code>) and Arabic
        (<code>ar</code>) with this text, and enter its name above:
      </p>
      <CopyLine text={setup.template_body_en} />
      <CopyLine text={setup.template_body_ar} rtl />
    </div>
  );
}

function CopyLine({ text, rtl }: { text: string; rtl?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <div className="mt-2 flex items-start gap-2 rounded-md border border-[var(--border)] bg-white p-2">
      <span className="flex-1" dir={rtl ? "rtl" : "ltr"}>{text}</span>
      <button
        onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {}); }}
        aria-label="Copy" className="shrink-0 text-slate-400 hover:text-slate-700"
      >
        {done ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}