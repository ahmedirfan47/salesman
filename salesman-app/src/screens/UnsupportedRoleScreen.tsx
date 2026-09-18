import { View, Text, StyleSheet } from "react-native";
import { colors, spacing, typography } from "../theme/theme";

export function UnsupportedRoleScreen() {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>This app is for drivers and dispatchers</Text>
      <Text style={styles.body}>
        Your account doesn't have a driver or dispatcher role, so there's nothing for you here
        yet. Use the web dashboard to manage products, pricing, orders, and your team.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, backgroundColor: colors.bg },
  title: { ...typography.title, color: colors.text, textAlign: "center", marginBottom: spacing.sm },
  body: { ...typography.body, color: colors.textMuted, textAlign: "center", lineHeight: 22 },
});