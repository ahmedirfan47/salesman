import { View, Text, Pressable, StyleSheet } from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import type { BillingPeriod, Plan } from "../data/plans";

interface Props {
  plan: Plan;
  period: BillingPeriod;
  selected: boolean;
  onSelect: (planId: string) => void;
}

function Check() {
  return (
    <View style={styles.checkWrap}>
      <Text style={styles.checkMark}>✓</Text>
    </View>
  );
}

export function PlanCard({ plan, period, selected, onSelect }: Props) {
  const price =
    period === "annual" ? plan.annualMonthlyPrice : plan.monthlyPrice;

  return (
    <Pressable
      onPress={() => onSelect(plan.id)}
      style={[styles.card, selected && styles.cardSelected]}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={`${plan.name} plan. ${plan.tagline}.`}
    >
      {plan.recommended && (
        <View style={styles.ribbon}>
          <Text style={styles.ribbonText}>MOST POPULAR</Text>
        </View>
      )}

      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.name}>{plan.name}</Text>
          <Text style={styles.tagline}>{plan.tagline}</Text>
        </View>
        <View style={[styles.radio, selected && styles.radioSelected]}>
          {selected && <View style={styles.radioInner} />}
        </View>
      </View>

      <View style={styles.priceRow}>
        {plan.custom ? (
          <Text style={styles.customPrice}>Custom pricing</Text>
        ) : plan.free ? (
          <>
            <Text style={styles.price}>Free</Text>
            <Text style={styles.per}>forever</Text>
          </>
        ) : (
          <>
            <Text style={styles.currency}>{plan.currency}</Text>
            <Text style={styles.price}>{price.toLocaleString()}</Text>
            <Text style={styles.per}>/month</Text>
          </>
        )}
      </View>
      {!plan.custom && !plan.free && period === "annual" && (
        <Text style={styles.billedNote}>billed annually</Text>
      )}

      <View style={styles.divider} />

      <View style={styles.features}>
        {plan.features.map((f) => (
          <View key={f} style={styles.featureRow}>
            <Check />
            <Text style={styles.featureText}>{f}</Text>
          </View>
        ))}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.white,
    borderRadius: radius.xl,
    borderWidth: 1.5,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  cardSelected: {
    borderColor: colors.accent,
    backgroundColor: colors.accentDim,
  },
  ribbon: {
    alignSelf: "flex-start",
    backgroundColor: colors.accent,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.sm,
    marginBottom: spacing.sm + 2,
  },
  ribbonText: { ...typography.tiny, color: colors.white },
  headerRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  name: { ...typography.title, color: colors.text },
  tagline: {
    ...typography.caption,
    color: colors.textMuted,
    marginTop: 2,
    lineHeight: 18,
  },
  radio: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: colors.borderStrong,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  radioSelected: { borderColor: colors.accent },
  radioInner: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.accent,
  },
  priceRow: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: spacing.xs,
    marginTop: spacing.md,
  },
  currency: { ...typography.body, color: colors.textMuted },
  price: { fontSize: 34, fontWeight: "700", color: colors.text, letterSpacing: -1 },
  per: { ...typography.body, color: colors.textMuted },
  customPrice: { ...typography.title, color: colors.text, marginTop: 2 },
  billedNote: { ...typography.caption, color: colors.textDim, marginTop: 2 },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: spacing.md,
  },
  features: { gap: spacing.sm + 2 },
  featureRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm + 2 },
  checkWrap: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.accentDim,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 1,
  },
  checkMark: { fontSize: 11, color: colors.accent, fontWeight: "700" },
  featureText: { ...typography.body, color: colors.textMuted, flex: 1, lineHeight: 21 },
});