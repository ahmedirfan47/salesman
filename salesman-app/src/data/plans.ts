/**
 * Salesman pricing for the mobile app. Mirrors dashboard/lib/plans.ts --
 * keep the two in step when commercial terms change.
 *
 * Commercial model: priced per branch. Each branch has a one-time setup fee
 * and a monthly subscription. Prices in USD, excluding VAT.
 */
export const PRICING = {
  currency: "USD",
  setupPerBranch: 11000,
  monthlyPerBranch: 1050,
  maxBranches: 50,
} as const;

/** Only capabilities Salesman has today. */
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