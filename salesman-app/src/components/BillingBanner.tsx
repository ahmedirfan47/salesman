import { View, Text, StyleSheet } from "react-native";
import { TriangleAlert } from "lucide-react-native";
import { colors, spacing, typography } from "../theme/theme";
import { useAuth } from "../lib/auth-context";

/**
 * Same notice the dashboard shows when the business has unpaid invoices.
 * Once the account is read-only every change fails with the server's 402
 * message, so the banner explains why before anyone tries.
 */
export function BillingBanner() {
  const { me } = useAuth();
  if (!me?.billing_message || me.billing_state === "ok") return null;
  const blocked = me.billing_state === "read_only";
  const fg = blocked ? colors.danger : colors.warning;
  return (
    <View style={[styles.banner, { backgroundColor: blocked ? colors.dangerDim : colors.warningDim }]}>
      <TriangleAlert size={16} color={fg} />
      <Text style={[styles.text, { color: fg }]}>{me.billing_message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
  },
  text: { ...typography.caption, flex: 1, fontWeight: "500", lineHeight: 18 },
});