/** Display helpers shared by every screen. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "SAR 1,250.00" -- amounts arrive from the API as strings or numbers. */
export function money(amount: string | number | null | undefined, currency?: string | null): string {
  const n = Number(amount ?? 0);
  const text = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${currency} ${text}` : text;
}

/** "9 Nov 2026" -- same format as the dashboard. */
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "14:05" in the phone's local time. */
export function time(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** "Today 14:05", "Yesterday 09:30" or "9 Nov 14:05". */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return `Today ${time(iso)}`;
  if (same(d, yesterday)) return `Yesterday ${time(iso)}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${time(iso)}`;
}

/** "just now", "5 min ago", "3 h ago", "2 d ago", else a date. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  return days < 30 ? `${days} d ago` : day(iso);
}

/** YYYY-MM-DD for the phone's local date, offset by `delta` days. */
export function isoDate(delta = 0, from = new Date()): string {
  const d = new Date(from);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Digits only, for wa.me and tel: links. */
export function digits(phone: string | null | undefined): string {
  return (phone ?? "").replace(/\D/g, "");
}

export function errorText(e: unknown, fallback = "Something went wrong"): string {
  return e instanceof Error ? e.message : fallback;
}