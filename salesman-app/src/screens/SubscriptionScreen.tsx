import { useMemo, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  StyleSheet,
  SafeAreaView,
  Platform,
  StatusBar,
} from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { plans, annualSavingsPercent, type BillingPeriod } from "../data/plans";
import { PlanCard } from "../components/PlanCard";
import { BillingToggle } from "../components/BillingToggle";

interface Props {
  /** Called with the chosen plan id once the user continues. Wire this to
   *  the real checkout/payment flow when billing is implemented. */
  onContinue?: (planId: string, period: BillingPeriod) => void;
  /** Lets an existing customer skip straight to sign-in. */
  onSignIn?: () => void;
}

export function SubscriptionScreen({ onContinue, onSignIn }: Props) {
  const [period, setPeriod] = useState<BillingPeriod>("annual");
  const recommended = plans.find((p) => p.recommended) ?? plans[0];
  const [selectedId, setSelectedId] = useState<string>(recommended.id);

  const savings = useMemo(() => annualSavingsPercent(recommended), [recommended]);
  const selectedPlan = plans.find((p) => p.id === selectedId) ?? recommended;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.brandRow}>
          <Text style={styles.brand}>SALESMAN</Text>
          <Text style={styles.byline}>by Sonic</Text>
        </View>

        <Text style={styles.headline}>
          Run your orders and deliveries on autopilot.
        </Text>
        <Text style={styles.sub}>
          Your customers keep ordering on WhatsApp. Salesman handles the
          pricing, the stock, and the delivery behind it.
        </Text>

        <View style={styles.toggleWrap}>
          <BillingToggle
            value={period}
            onChange={setPeriod}
            savingsPercent={savings}
          />
        </View>

        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            period={period}
            selected={plan.id === selectedId}
            onSelect={setSelectedId}
          />
        ))}

        <Text style={styles.finePrint}>
          Free plan needs no card. Paid prices exclude VAT and are billed in
          USD. Cancel anytime. Limits apply per organization, not per user.
        </Text>
      </ScrollView>

      {/* Sticky action footer -- keeps the primary CTA reachable without scrolling */}
      <View style={styles.footer}>
        <Pressable
          style={styles.cta}
          onPress={() => onContinue?.(selectedPlan.id, period)}
          accessibilityRole="button"
          accessibilityLabel={
            selectedPlan.custom
              ? "Contact sales about this plan"
              : selectedPlan.free
              ? "Start using the Free plan"
              : `Continue with the ${selectedPlan.name} plan`
          }
        >
          <Text style={styles.ctaText}>
            {selectedPlan.custom
              ? "Contact sales"
              : selectedPlan.free
              ? "Start free"
              : `Continue with ${selectedPlan.name}`}
          </Text>
        </Pressable>

        <Pressable
          onPress={onSignIn}
          style={styles.signInWrap}
          accessibilityRole="button"
          accessibilityLabel="Sign in to an existing account"
        >
          <Text style={styles.signInText}>
            Already have an account? <Text style={styles.signInLink}>Sign in</Text>
          </Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingTop: Platform.OS === "android" ? StatusBar.currentHeight ?? 0 : 0,
  },
  scroll: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xl,
  },
  brandRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.sm },
  brand: { ...typography.heading, color: colors.text, letterSpacing: 1.5 },
  byline: { ...typography.caption, color: colors.textDim },
  headline: {
    ...typography.display,
    color: colors.text,
    marginTop: spacing.lg,
    lineHeight: 38,
  },
  sub: {
    ...typography.body,
    color: colors.textMuted,
    marginTop: spacing.sm + 2,
    lineHeight: 22,
  },
  toggleWrap: { marginTop: spacing.lg, marginBottom: spacing.lg },
  finePrint: {
    ...typography.caption,
    color: colors.textDim,
    textAlign: "center",
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  footer: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.white,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
    gap: spacing.sm + 4,
  },
  cta: {
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 16,
    alignItems: "center",
  },
  ctaText: { ...typography.heading, color: colors.white },
  signInWrap: { alignItems: "center" },
  signInText: { ...typography.caption, color: colors.textMuted },
  signInLink: { color: colors.accent, fontWeight: "600" },
});