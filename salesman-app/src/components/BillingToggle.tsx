import { View, Text, Pressable, StyleSheet } from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import type { BillingPeriod } from "../data/plans";

interface Props {
  value: BillingPeriod;
  onChange: (period: BillingPeriod) => void;
  savingsPercent: number;
}

/** Segmented monthly/annual control. Annual shows the savings badge -- the
 * standard nudge toward the higher-commitment plan without being pushy. */
export function BillingToggle({ value, onChange, savingsPercent }: Props) {
  return (
    <View style={styles.wrap}>
      {(["monthly", "annual"] as BillingPeriod[]).map((period) => {
        const active = value === period;
        return (
          <Pressable
            key={period}
            onPress={() => onChange(period)}
            style={[styles.segment, active && styles.segmentActive]}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={
              period === "annual"
                ? `Annual billing, save ${savingsPercent} percent`
                : "Monthly billing"
            }
          >
            <Text style={[styles.label, active && styles.labelActive]}>
              {period === "monthly" ? "Monthly" : "Annual"}
            </Text>
            {period === "annual" && savingsPercent > 0 && (
              <View style={[styles.badge, active && styles.badgeActive]}>
                <Text style={[styles.badgeText, active && styles.badgeTextActive]}>
                  −{savingsPercent}%
                </Text>
              </View>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    padding: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  segment: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs + 2,
    paddingVertical: 9,
    borderRadius: radius.pill,
  },
  segmentActive: {
    backgroundColor: colors.white,
    shadowColor: "#0E0F12",
    shadowOpacity: 0.06,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  label: { ...typography.bodyMedium, color: colors.textMuted },
  labelActive: { color: colors.text },
  badge: {
    backgroundColor: colors.surfaceStrong,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  badgeActive: { backgroundColor: colors.accentDim },
  badgeText: { ...typography.tiny, color: colors.textMuted },
  badgeTextActive: { color: colors.accent },
});