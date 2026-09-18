import { useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { useAuth } from "../lib/auth-context";
import { can } from "../lib/api";
import { Header } from "../components/Header";
import { DriverDeliveriesScreen } from "./DriverDeliveriesScreen";
import { DispatcherAssignmentsScreen } from "./DispatcherAssignmentsScreen";
import { UnsupportedRoleScreen } from "./UnsupportedRoleScreen";

type Tab = "deliveries" | "assignments";

/**
 * Routes a logged-in user to the right screen(s) based on their real
 * capabilities (not a raw role-name check) -- matching how the web
 * dashboard's sidebar decides what to show. A user with both driver and
 * dispatcher capabilities (e.g. an owner testing the app) gets a small
 * tab switcher; everyone else gets exactly one screen, no tabs.
 */
export function HomeScreen() {
  const { me } = useAuth();
  const isDriver = can(me, "deliver_order");
  const isDispatcher = can(me, "dispatch_order");
  const [tab, setTab] = useState<Tab>(isDriver ? "deliveries" : "assignments");

  if (!isDriver && !isDispatcher) {
    return (
      <>
        <Header title="Salesman" />
        <UnsupportedRoleScreen />
      </>
    );
  }

  const showBoth = isDriver && isDispatcher;

  return (
    <View style={styles.flex}>
      <Header title={tab === "deliveries" ? "My Deliveries" : "Assignment Queue"} />
      {showBoth && (
        <View style={styles.tabBar}>
          <Pressable
            style={[styles.tab, tab === "deliveries" && styles.tabActive]}
            onPress={() => setTab("deliveries")}
          >
            <Text style={[styles.tabText, tab === "deliveries" && styles.tabTextActive]}>Deliveries</Text>
          </Pressable>
          <Pressable
            style={[styles.tab, tab === "assignments" && styles.tabActive]}
            onPress={() => setTab("assignments")}
          >
            <Text style={[styles.tabText, tab === "assignments" && styles.tabTextActive]}>Assignments</Text>
          </Pressable>
        </View>
      )}
      <View style={styles.flex}>
        {tab === "deliveries" ? <DriverDeliveriesScreen /> : <DispatcherAssignmentsScreen />}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  tabBar: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    backgroundColor: colors.white,
  },
  tab: { paddingVertical: 8, paddingHorizontal: 4, borderBottomWidth: 2, borderBottomColor: "transparent" },
  tabActive: { borderBottomColor: colors.accent },
  tabText: { ...typography.bodyMedium, color: colors.textDim },
  tabTextActive: { color: colors.accent },
});