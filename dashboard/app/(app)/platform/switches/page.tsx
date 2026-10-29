"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { when, type SettingsResponse, type SiteSettings } from "@/lib/console";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Info, Lock, LogIn, Megaphone, UserPlus } from "lucide-react";

export default function SwitchesPage() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [form, setForm] = useState<SiteSettings | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/platform/settings")
      .then((r: SettingsResponse) => { setData(r); setForm(r.settings); })
      .catch((e) => setError(e.message));
  }, []);

  async function save(changes: Partial<SiteSettings>, done: string) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r: SettingsResponse = await api("/platform/settings", { method: "PUT", body: JSON.stringify(changes) });
      setData(r);
      setForm(r.settings);
      setMsg(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (!data || !form) return error ? <p className="text-sm text-red-600">{error}</p> : <p className="text-slate-400">Loading…</p>;
  const s = data.settings;

  return (
    <div className="max-w-3xl space-y-4">
      <p className="text-sm text-slate-500">
        These apply to the web dashboard and the mobile app straight away (within about 10 seconds). The WhatsApp agent keeps
        serving customers whatever you choose. You always keep access as a Stonic admin.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {msg && <p className="text-sm text-emerald-700">{msg}</p>}

      <SwitchCard
        icon={LogIn} title="Sign-in" on={s.sign_in_enabled} busy={busy}
        onText="Open: everyone with an account can sign in."
        offText="Closed: only Stonic admins can sign in. Everyone else is signed out on their next click."
        onToggle={() => save({ sign_in_enabled: !s.sign_in_enabled }, s.sign_in_enabled ? "Sign-in is closed." : "Sign-in is open.")}
      >
        <label className="mt-3 block text-xs font-medium text-slate-500">Message on the sign-in page while it is closed</label>
        <textarea className="mt-1 w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm" rows={2} maxLength={500}
          value={form.closed_message} onChange={(e) => setForm({ ...form, closed_message: e.target.value })} />
        <Button variant="outline" className="mt-2" disabled={busy || form.closed_message === s.closed_message}
          onClick={() => save({ closed_message: form.closed_message }, "Message saved.")}>Save message</Button>
      </SwitchCard>

      <SwitchCard
        icon={UserPlus} title="Sign-up" on={s.sign_up_enabled} busy={busy}
        onText={s.sign_in_enabled ? "Open: new businesses can create an account." : "Open, but has no effect while sign-in is closed."}
        offText={'Closed: the sign-up page says so and "Create an account" links are hidden.'}
        onToggle={() => save({ sign_up_enabled: !s.sign_up_enabled }, s.sign_up_enabled ? "Sign-up is closed." : "Sign-up is open.")}
      />

      <SwitchCard
        icon={Lock} title="Read-only mode" on={s.read_only} busy={busy} onIsWarning
        onText="On: everyone can look, nobody but Stonic can change anything. Use it for maintenance or a data move."
        offText="Off: everything works normally."
        onToggle={() => save({ read_only: !s.read_only }, s.read_only ? "Read-only mode is off." : "Read-only mode is on.")}
      >
        <label className="mt-3 block text-xs font-medium text-slate-500">Message shown when someone tries to change something</label>
        <textarea className="mt-1 w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm" rows={2} maxLength={500}
          value={form.read_only_message} onChange={(e) => setForm({ ...form, read_only_message: e.target.value })} />
        <Button variant="outline" className="mt-2" disabled={busy || form.read_only_message === s.read_only_message}
          onClick={() => save({ read_only_message: form.read_only_message }, "Message saved.")}>Save message</Button>
      </SwitchCard>

      <Card className="p-5">
        <div className="flex items-start gap-3">
          <Megaphone size={20} className="mt-0.5 shrink-0 text-[var(--primary)]" />
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold">Announcement banner</h2>
            <p className="text-sm text-slate-500">Shown at the top of every page for everyone signed in. Leave it empty to hide it.</p>
            <textarea className="mt-3 w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm" rows={2} maxLength={300}
              placeholder="e.g. Odoo sync is now live. Connect it under Integrations."
              value={form.banner_text} onChange={(e) => setForm({ ...form, banner_text: e.target.value })} />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {(["info", "warning"] as const).map((tone) => (
                <button key={tone} onClick={() => setForm({ ...form, banner_tone: tone })}
                  className={`rounded-full border px-3 py-1 text-xs font-medium ${form.banner_tone === tone ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "border-[var(--border)] bg-white text-slate-600"}`}>
                  {tone === "info" ? "Information" : "Warning"}
                </button>
              ))}
              <Button className="ml-auto" disabled={busy || (form.banner_text === s.banner_text && form.banner_tone === s.banner_tone)}
                onClick={() => save({ banner_text: form.banner_text, banner_tone: form.banner_tone }, form.banner_text.trim() ? "Banner saved." : "Banner removed.")}>
                Save banner
              </Button>
            </div>
            {form.banner_text.trim() && (
              <div className={`mt-3 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${form.banner_tone === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-indigo-100 bg-indigo-50 text-slate-700"}`}>
                {form.banner_tone === "warning" ? <AlertTriangle size={16} className="mt-0.5 shrink-0" /> : <Info size={16} className="mt-0.5 shrink-0 text-[var(--primary)]" />}
                <span>{form.banner_text}</span>
              </div>
            )}
          </div>
        </div>
      </Card>

      <p className="text-xs text-slate-400">
        Stonic admins: {data.admin_emails.join(", ")}. Last changed {when(data.updated_at)}{data.updated_by ? ` by ${data.updated_by}` : ""}.
      </p>
    </div>
  );
}

function SwitchCard({ icon: Icon, title, on, onText, offText, onToggle, busy, onIsWarning, children }: {
  icon: React.ComponentType<{ size?: number; className?: string }>; title: string; on: boolean; onText: string; offText: string;
  onToggle: () => void; busy: boolean; onIsWarning?: boolean; children?: React.ReactNode;
}) {
  const alert = onIsWarning ? on : !on;
  return (
    <Card className={`p-5 ${alert ? "border-amber-300" : ""}`}>
      <div className="flex items-start gap-3">
        <Icon size={20} className={`mt-0.5 shrink-0 ${alert ? "text-amber-600" : "text-[var(--primary)]"}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">{title}</h2>
            <button role="switch" aria-checked={on} aria-label={title} disabled={busy} onClick={onToggle}
              className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition disabled:opacity-50 ${on ? (onIsWarning ? "bg-amber-500" : "bg-emerald-500") : "bg-slate-300"}`}>
              <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${on ? "translate-x-5" : "translate-x-0.5"}`} />
            </button>
          </div>
          <p className={`mt-1 text-sm ${alert ? "text-amber-800" : "text-slate-500"}`}>{on ? onText : offText}</p>
          {children}
        </div>
      </div>
    </Card>
  );
}