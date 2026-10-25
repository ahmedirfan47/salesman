export type BillingPeriod = "monthly" | "annual";

export interface Plan {
  id: string;
  name: string;
  tagline: string;
  monthly: number;
  annualMonthly: number;
  currency: string;
  free?: boolean;
  recommended?: boolean;
  features: string[];
}

/**
 * SINGLE SOURCE OF TRUTH for Salesman's pricing.
 * Both the public pricing page (/plans) and the authenticated billing page
 * (/billing) import from here -- change a price or a feature once, and it's
 * correct everywhere. Never hardcode a plan's numbers in a page again.
 */
export const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    tagline: "Get your catalog and orders out of spreadsheets",
    monthly: 0,
    annualMonthly: 0,
    currency: "USD",
    free: true,
    features: [
      "Up to 50 orders / month",
      "AI ordering agent over WhatsApp",
      "Live pricing & inventory",
      "Up to 2 team members",
      "Community support",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    tagline: "For distributors running a delivery fleet",
    monthly: 35,
    annualMonthly: 29,
    currency: "USD",
    recommended: true,
    features: [
      "Up to 2,000 orders / month",
      "Everything in Free",
      "Delivery zones & auto-assignment",
      "Driver & dispatcher apps",
      "Unlimited team members",
      "Daily reports & print queue",
      "Priority support",
    ],
  },
  {
    id: "scale",
    name: "Scale",
    tagline: "For multi-branch and high-volume operations",
    monthly: 200,
    annualMonthly: 167,
    currency: "USD",
    features: [
      "Unlimited orders",
      "Everything in Growth",
      "Multi-branch operations",
      "Cost & margin analytics",
      "Dedicated onboarding",
      "Custom integrations",
      "SLA & account manager",
    ],
  },
];

export function annualSavingsPercent(planId = "growth"): number {
  const plan = plans.find((p) => p.id === planId);
  if (!plan || plan.free || plan.monthly === 0) return 0;
  return Math.round(((plan.monthly - plan.annualMonthly) / plan.monthly) * 100);
}/**
 * SINGLE SOURCE OF TRUTH for Salesman's pricing on the web.
 * The public pricing page (/plans) and the authenticated billing page
 * (/billing) both read from here -- change a number once and it's correct
 * everywhere. The mobile app mirrors this in salesman-app/src/data/plans.ts.
 *
 * Commercial model: priced per branch. Each branch has a one-time setup fee
 * (onboarding, price-sheet import, WhatsApp number, zones and team set-up)
 * and a monthly subscription.
 */
export const PRICING = {
  currency: "USD",
  setupPerBranch: 11000,
  monthlyPerBranch: 1050,
  maxBranches: 50,
} as const;

/** Only capabilities Salesman has today -- no roadmap items, no integrations it lacks. */
export const INCLUDED_FEATURES: string[] = [
  "AI salesman on WhatsApp — Arabic and English, text and voice notes",
  "Quotes from your active price list, uploaded from your Excel sheet",
  "Live stock on every quote, with your team approving exceptions",
  "Orders, warehouse print queue and delivery zones with auto-assignment",
  "Driver and dispatcher apps",
  "Daily PDF reports and owner analytics (margins, cost prices)",
  "Setup and onboarding by the Stonic team",
];

export const SALES_EMAIL = "ahmedirfanmail@gmail.com";

export interface Quote {
  branches: number;
  setup: number;
  monthly: number;
  firstYear: number;
}

export function quote(branches: number): Quote {
  const b = Math.min(PRICING.maxBranches, Math.max(1, Math.floor(branches) || 1));
  const setup = b * PRICING.setupPerBranch;
  const monthly = b * PRICING.monthlyPerBranch;
  return { branches: b, setup, monthly, firstYear: setup + monthly * 12 };
}

export function formatMoney(n: number): string {
  return `$${n.toLocaleString("en-US")}`;
}