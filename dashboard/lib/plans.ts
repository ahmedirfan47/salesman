/**
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
  "Mobile app for salesmen, drivers and dispatchers",
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