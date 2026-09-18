import { View, Text, Pressable, StyleSheet, SafeAreaView } from "react-native";
import { colors, spacing, typography } from "../theme/theme";
import { useAuth } from "../lib/auth-context";

export function Header({ title }: { title: string }) {
  const { me, logout } = useAuth();
  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.row}>
        <View>
          <Text style={styles.title}>{title}</Text>
          {me && (
            <Text style={styles.subtitle}>
              {me.full_name || me.email} · <Text style={{ textTransform: "capitalize" }}>{me.role}</Text>
            </Text>
          )}
        </View>
        <Pressable onPress={logout} hitSlop={8}>
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
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 4,
  },
  title: { ...typography.heading, color: colors.text },
  subtitle: { ...typography.tiny, color: colors.textDim, marginTop: 2, textTransform: "none" },
  signOut: { ...typography.caption, color: colors.accent, fontWeight: "600" },
});