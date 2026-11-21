/**
 * Salesman pricing for the mobile app. A copy of dashboard/lib/plans.ts --
 * keep the two (and PLANS in backend/app/modules/billing/service.py) in step.
 *
 * Commercial model: three plans, priced per branch in SAR, excluding VAT.
 * Pilot: 60 days to prove it on your own orders, no setup fee.
 * Growth: for distributors running on Salesman; orders above the included
 * number are billed on the next monthly invoice.
 * Enterprise: multi-branch groups, unlimited orders, ERP integration, SLA.
 */
export type PlanKey = "pilot" | "growth" | "enterprise";

export interface Plan {
  key: PlanKey;
  name: string;
  tagline: string;
  setupPerBranch: number;
  monthlyPerBranch: number;
  /** orders included per branch per month; null = unlimited */
  includedOrders: number | null;
  /** charged per order above the included orders */
  overagePerOrder: number | null;
  minBranches: number;
  maxBranches: number;
  features: string[];
  highlight?: boolean;
}

export const CURRENCY = "SAR";

export const PLANS: Plan[] = [
  {
    key: "pilot",
    name: "Pilot",
    tagline: "60 days on your real WhatsApp orders. No setup fee.",
    setupPerBranch: 0,
    monthlyPerBranch: 2500,
    includedOrders: 2000,
    overagePerOrder: 0.6,
    minBranches: 1,
    maxBranches: 1,
    features: [
      "One branch and its WhatsApp number",
      "Shadow mode in week one: your team approves every AI order",
      "Written success target agreed up front",
      "Weekly accuracy and time-saved report",
    ],
  },
  {
    key: "growth",
    name: "Growth",
    tagline: "For distributors taking orders on Salesman every day.",
    setupPerBranch: 7500,
    monthlyPerBranch: 3500,
    includedOrders: 5000,
    overagePerOrder: 0.6,
    minBranches: 1,
    maxBranches: 10,
    highlight: true,
    features: [
      "Everything in Pilot, for up to 10 branches",
      "Payment reminders and statements on WhatsApp",
      "Customer credit limits and overdue holds",
      "ZATCA e-invoices from every order",
    ],
  },
  {
    key: "enterprise",
    name: "Enterprise",
    tagline: "Multi-branch groups with their own ERP and security review.",
    setupPerBranch: 10000,
    monthlyPerBranch: 4000,
    includedOrders: null,
    overagePerOrder: null,
    minBranches: 3,
    maxBranches: 50,
    features: [
      "Unlimited orders",
      "ERP connection set up with your team (Odoo first)",
      "Named support contact and a written service agreement",
      "Security pack for your IT review",
    ],
  },
];

/** What every plan includes -- only capabilities Salesman has today. */
export const INCLUDED_FEATURES: string[] = [
  "AI salesman on WhatsApp — Arabic and English, text and voice notes",
  "Understands each customer's own words for products, and learns from corrections",
  "\"Same as last time\" reorders from the customer's order history",
  "Holds doubtful orders for your team instead of guessing",
  "Live prices and stock from your price list, with your team approving exceptions",
  "Orders, warehouse print queue and delivery zones with auto-assignment",
  "Mobile app for salesmen, drivers and dispatchers; daily reports and analytics",
];

export const SALES_EMAIL = "ahmedirfanmail@gmail.com";

export function planByKey(key: PlanKey): Plan {
  return PLANS.find((p) => p.key === key) ?? PLANS[0];
}

export interface Quote {
  plan: Plan;
  branches: number;
  setup: number;
  monthly: number;
  firstYear: number;
}

export function clampBranches(plan: Plan, branches: number): number {
  return Math.min(plan.maxBranches, Math.max(plan.minBranches, Math.floor(branches) || 1));
}

export function quote(key: PlanKey, branches: number): Quote {
  const plan = planByKey(key);
  const b = clampBranches(plan, branches);
  const setup = b * plan.setupPerBranch;
  const monthly = b * plan.monthlyPerBranch;
  // a pilot runs for two months
  const firstYear = key === "pilot" ? monthly * 2 : setup + monthly * 12;
  return { plan, branches: b, setup, monthly, firstYear };
}

export function formatMoney(n: number): string {
  const digits = Number.isInteger(n) ? 0 : 2;
  return `${CURRENCY} ${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** The plan best suited to a number of branches, for pre-selecting on the pricing page. */
export function suggestedPlan(branches: number): PlanKey {
  if (branches >= 3) return "enterprise";
  return "growth";
}
