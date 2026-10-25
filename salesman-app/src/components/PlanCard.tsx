import { View, Text, Pressable, StyleSheet } from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { INCLUDED_FEATURES, PRICING, formatMoney, quote } from "../data/plans";

interface Props {
  branches: number;
  onBranchesChange: (n: number) => void;
}

function Check() {
  return (
    <View style={styles.checkWrap}>
      <Text style={styles.checkMark}>✓</Text>
    </View>
  );
}

function Stepper({ label, onPress, disabled }: { label: string; onPress: () => void; disabled: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[styles.stepBtn, disabled && styles.stepBtnDisabled]}
      accessibilityRole="button"
      accessibilityLabel={label === "−" ? "Fewer branches" : "More branches"}
    >
      <Text style={styles.stepText}>{label}</Text>
    </Pressable>
  );
}

/** The single Salesman plan: per-branch setup + monthly, with a live quote. */
export function PlanCard({ branches, onBranchesChange }: Props) {
  const q = quote(branches);

  return (
    <View style={styles.card}>
      <Text style={styles.name}>Salesman</Text>
      <Text style={styles.tagline}>One plan, priced per branch. Everything included.</Text>

      <View style={styles.priceGrid}>
        <View style={{ flex: 1 }}>
          <Text style={styles.priceLabel}>SETUP, PER BRANCH</Text>
          <Text style={styles.price}>{formatMoney(PRICING.setupPerBranch)}</Text>
          <Text style={styles.per}>one-time</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.priceLabel}>PER BRANCH</Text>
          <Text style={styles.price}>{formatMoney(PRICING.monthlyPerBranch)}</Text>
          <Text style={styles.per}>per month</Text>
        </View>
      </View>

      <View style={styles.divider} />

      <Text style={styles.branchLabel}>How many branches?</Text>
      <View style={styles.stepRow}>
        <Stepper label="−" onPress={() => onBranchesChange(q.branches - 1)} disabled={q.branches <= 1} />
        <Text style={styles.branchCount} accessibilityLiveRegion="polite">{q.branches}</Text>
        <Stepper label="+" onPress={() => onBranchesChange(q.branches + 1)} disabled={q.branches >= PRICING.maxBranches} />
      </View>

      <View style={styles.quote}>
        <View style={styles.quoteRow}>
          <Text style={styles.quoteKey}>Setup</Text>
          <Text style={styles.quoteVal}>{formatMoney(q.setup)}</Text>
        </View>
        <View style={styles.quoteRow}>
          <Text style={styles.quoteKey}>Monthly</Text>
          <Text style={styles.quoteVal}>{formatMoney(q.monthly)}/mo</Text>
        </View>
        <View style={[styles.quoteRow, styles.quoteTotal]}>
          <Text style={[styles.quoteKey, { color: colors.text, fontWeight: "600" }]}>First year total</Text>
          <Text style={[styles.quoteVal, { fontSize: 17 }]}>{formatMoney(q.firstYear)}</Text>
        </View>
      </View>

      <View style={styles.divider} />

      <View style={styles.features}>
        {INCLUDED_FEATURES.map((f) => (
          <View key={f} style={styles.featureRow}>
            <Check />
            <Text style={styles.featureText}>{f}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.white,
    borderRadius: radius.xl,
    borderWidth: 1.5,
    borderColor: colors.accent,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  name: { ...typography.title, color: colors.text },
  tagline: { ...typography.caption, color: colors.textMuted, marginTop: 2, lineHeight: 18 },
  priceGrid: { flexDirection: "row", gap: spacing.md, marginTop: spacing.md },
  priceLabel: { ...typography.tiny, color: colors.textDim },
  price: { fontSize: 28, fontWeight: "700", color: colors.text, letterSpacing: -0.8, marginTop: 4 },
  per: { ...typography.caption, color: colors.textDim },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.md },
  branchLabel: { ...typography.bodyMedium, color: colors.text },
  stepRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.sm },
  stepBtn: {
    width: 40, height: 40, borderRadius: 20, borderWidth: 1, borderColor: colors.borderStrong,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.white,
  },
  stepBtnDisabled: { opacity: 0.4 },
  stepText: { fontSize: 20, color: colors.text, fontWeight: "500" },
  branchCount: { fontSize: 24, fontWeight: "700", color: colors.text, minWidth: 40, textAlign: "center" },
  quote: { marginTop: spacing.md, gap: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md },
  quoteRow: { flexDirection: "row", justifyContent: "space-between" },
  quoteTotal: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm },
  quoteKey: { ...typography.body, color: colors.textMuted },
  quoteVal: { ...typography.bodyMedium, color: colors.text, fontWeight: "700" },
  features: { gap: spacing.sm + 2 },
  featureRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm + 2 },
  checkWrap: {
    width: 18, height: 18, borderRadius: 9, backgroundColor: colors.accentDim,
    alignItems: "center", justifyContent: "center", marginTop: 1,
  },
  checkMark: { fontSize: 11, color: colors.accent, fontWeight: "700" },
  featureText: { ...typography.body, color: colors.textMuted, flex: 1, lineHeight: 21 },
});