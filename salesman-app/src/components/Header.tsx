import { View, Text, Pressable, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors, spacing, typography } from "../theme/theme";
import { useAuth } from "../lib/auth-context";

export function Header({ title }: { title: string }) {
  const { me, logout } = useAuth();
  const branch = me?.branch_name ?? (me?.sees_all_branches ? "All branches" : null);
  return (
    <SafeAreaView edges={["top"]} style={styles.safe}>
      <View style={styles.row}>
        <View style={styles.text}>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
          {me && (
            <Text style={styles.subtitle} numberOfLines={1}>
              {me.full_name || me.email} · <Text style={styles.role}>{me.role}</Text>
              {branch ? ` · ${branch}` : ""}
            </Text>
          )}
        </View>
        <Pressable onPress={logout} hitSlop={8} accessibilityRole="button">
          <Text style={styles.signOut}>Sign out</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { backgroundColor: colors.white, borderBottomWidth: 1, borderBottomColor: colors.border },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 4,
  },
  text: { flex: 1 },
  title: { ...typography.heading, color: colors.text },
  subtitle: { fontSize: 12, color: colors.textDim, marginTop: 2 },
  role: { textTransform: "capitalize" },
  signOut: { ...typography.caption, color: colors.accent, fontWeight: "600" },
});