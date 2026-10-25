import { useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  StyleSheet,
  SafeAreaView,
  Platform,
  StatusBar,
  Linking,
} from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { SALES_EMAIL, quote } from "../data/plans";
import { PlanCard } from "../components/PlanCard";

interface Props {
  /** Lets an existing customer go straight to sign-in. Accounts are created
   *  by an admin from the web dashboard's Team & Access page. */
  onSignIn?: () => void;
}

export function SubscriptionScreen({ onSignIn }: Props) {
  const [branches, setBranches] = useState(1);

  function contactSales() {
    const b = quote(branches).branches;
    const subject = encodeURIComponent(`Salesman pilot — ${b} branch${b === 1 ? "" : "es"}`);
    Linking.openURL(`mailto:${SALES_EMAIL}?subject=${subject}`).catch(() => {});
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <View style={styles.brandRow}>
          <Text style={styles.brand}>SALESMAN</Text>
          <Text style={styles.byline}>by Stonic</Text>
        </View>

        <Text style={styles.headline}>Run your orders and deliveries on autopilot.</Text>
        <Text style={styles.sub}>
          Your customers keep ordering on WhatsApp. Salesman handles the pricing, the stock, and the delivery
          behind it.
        </Text>

        <View style={{ height: spacing.lg }} />
        <PlanCard branches={branches} onBranchesChange={setBranches} />

        <Text style={styles.finePrint}>Prices in USD, excluding VAT.</Text>
      </ScrollView>

      {/* Sticky action footer -- keeps the primary CTA reachable without scrolling */}
      <View style={styles.footer}>
        <Pressable
          style={styles.cta}
          onPress={contactSales}
          accessibilityRole="button"
          accessibilityLabel="Email the Stonic team about a pilot"
        >
          <Text style={styles.ctaText}>Talk to us about a pilot</Text>
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
  scroll: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.xl },
  brandRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.sm },
  brand: { ...typography.heading, color: colors.text, letterSpacing: 1.5 },
  byline: { ...typography.caption, color: colors.textDim },
  headline: { ...typography.display, color: colors.text, marginTop: spacing.lg, lineHeight: 38 },
  sub: { ...typography.body, color: colors.textMuted, marginTop: spacing.sm + 2, lineHeight: 22 },
  finePrint: { ...typography.caption, color: colors.textDim, textAlign: "center", lineHeight: 18, marginTop: spacing.sm },
  footer: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.white,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
    gap: spacing.sm + 4,
  },
  cta: { backgroundColor: colors.accent, borderRadius: radius.pill, paddingVertical: 16, alignItems: "center" },
  ctaText: { ...typography.heading, color: colors.white },
  signInWrap: { alignItems: "center" },
  signInText: { ...typography.caption, color: colors.textMuted },
  signInLink: { color: colors.accent, fontWeight: "600" },
});