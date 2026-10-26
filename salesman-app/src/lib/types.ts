import type { Tone } from "../components/ui";

/** API shapes used by the app (mirrors backend/app/schemas). */

export type OrderStatus =
  | "requires_human_review"
  | "confirmed"
  | "preparing"
  | "dispatched"
  | "delivered"
  | "completed"
  | "cancelled";

export type OrderItem = {
  id: string;
  sku: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  available_at_order: number | null;
};

export type Order = {
  id: string;
  branch_id: string;
  order_number: string;
  status: OrderStatus | string;
  customer_name: string | null;
  customer_company: string | null;
  whatsapp_number: string | null;
  total_amount: string;
  currency: string;
  confirmed_at: string | null;
  created_at: string;
  zone_id: string | null;
  assigned_driver_id: string | null;
  items: OrderItem[];
};

export type OrderEvent = {
  from_status: string | null;
  to_status: string;
  actor_name: string | null;
  note: string | null;
  created_at: string;
};

export type OrderDetail = Order & { events: OrderEvent[] };

export const ORDER_STATUS: Record<string, { label: string; tone: Tone }> = {
  requires_human_review: { label: "Needs approval", tone: "warning" },
  confirmed: { label: "Confirmed", tone: "accent" },
  preparing: { label: "Preparing", tone: "violet" },
  dispatched: { label: "On the way", tone: "violet" },
  delivered: { label: "Delivered", tone: "success" },
  completed: { label: "Completed", tone: "success" },
  cancelled: { label: "Cancelled", tone: "danger" },
};

export function orderStatus(status: string) {
  return ORDER_STATUS[status] ?? { label: status.replace(/_/g, " "), tone: "neutral" as Tone };
}

export type Customer = {
  id: string;
  branch_id: string;
  name: string;
  company: string | null;
  whatsapp_number: string | null;
  address: string | null;
  zone_id: string | null;
  is_active: boolean;
};

export type CatalogRow = {
  id: string;
  sku: string;
  name_en: string;
  name_ar: string | null;
  category: string | null;
  is_active: boolean;
  unit_price: number | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  stock: number;
};

export type ProspectStatus = "new" | "contacted" | "interested" | "won" | "lost";

export type Prospect = {
  id: string;
  branch_id: string | null;
  kind: "new" | "winback";
  source: string;
  status: ProspectStatus;
  name: string;
  contact_name: string | null;
  phone: string | null;
  phone_digits: string | null;
  address: string | null;
  area: string | null;
  category: string | null;
  zone_id: string | null;
  zone_name: string | null;
  google_maps_uri: string | null;
  insight: string | null;
  notes: string | null;
  lost_reason: string | null;
  assigned_to_id: string | null;
  assigned_to_name: string | null;
  customer_id: string | null;
  last_contacted_at: string | null;
  closed_at: string | null;
  created_at: string;
  priority: "high" | "medium" | "low";
  priority_reasons: string[];
};

export type Activity = {
  id: string;
  kind: string;
  body: string | null;
  actor_name: string | null;
  created_at: string;
};

export type ProspectDetail = Prospect & { activities: Activity[] };

export const PROSPECT_STATUS: Record<ProspectStatus, { label: string; tone: Tone }> = {
  new: { label: "New", tone: "neutral" },
  contacted: { label: "Contacted", tone: "accent" },
  interested: { label: "Interested", tone: "warning" },
  won: { label: "Won", tone: "success" },
  lost: { label: "Lost", tone: "danger" },
};

export const PRIORITY_TONE: Record<Prospect["priority"], Tone> = {
  high: "success",
  medium: "warning",
  low: "neutral",
};

export type Zone = { id: string; name: string };

export type Escalation = {
  id: string;
  branch_id: string;
  reason_type: string;
  context: {
    order_number?: string;
    shortfalls?: { sku: string; requested: number; available: number }[];
    [key: string]: unknown;
  };
  ai_recommendation: string | null;
  order_id: string | null;
  customer_name: string | null;
  status: string;
  resolution: string | null;
  created_at: string;
};

export type DailySummary = {
  date: string;
  currency: string;
  totals: {
    total_orders: number;
    confirmed_orders: number;
    cancelled_orders: number;
    review_orders: number;
    total_revenue: number;
    avg_order_value: number;
    total_units_sold: number;
  };
  products_sold: { sku: string; name: string; qty: number; revenue: number }[];
  remaining_stock: { sku: string; name: string; quantity: number }[];
  orders: { order_number: string; customer: string; status: string; total: number; time: string }[];
};