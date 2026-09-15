export type BillingPeriod = "monthly" | "annual";

export interface Plan {
  id: string;
  name: string;
  /** Short line under the plan name explaining who it's for. */
  tagline: string;
  monthlyPrice: number;
  /** Effective per-month price when billed annually. */
  annualMonthlyPrice: number;
  currency: string;
  features: string[];
  /** Highlighted as the default/suggested choice. */
  recommended?: boolean;
  /** Renders as "Contact us" rather than a price. */
  custom?: boolean;
  /** Free plan -- shows "Free" instead of a price, and a different CTA. */
  free?: boolean;
}

/**
 * Salesman pricing. Free tier is a real free plan (no card required);
 * paid tiers are billed in USD.
 * Annual pricing gives ~2 months free (16-17% off) -- adjust if the
 * commercial terms change.
 */
export const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    tagline: "Get your catalog and orders out of spreadsheets",
    monthlyPrice: 0,
    annualMonthlyPrice: 0,
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
    monthlyPrice: 35,
    annualMonthlyPrice: 29,
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
    monthlyPrice: 200,
    annualMonthlyPrice: 167,
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

/** Percentage saved by paying annually, derived from the Growth plan. */
export function annualSavingsPercent(plan: Plan): number {
  if (plan.custom || plan.free || plan.monthlyPrice === 0) return 0;
  const saved = (plan.monthlyPrice - plan.annualMonthlyPrice) / plan.monthlyPrice;
  return Math.round(saved * 100);
}