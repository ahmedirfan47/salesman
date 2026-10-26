import { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { ClipboardList, ShieldCheck, ChartColumn, Target, Truck, Route } from "lucide-react-native";
import { colors, spacing, typography } from "../theme/theme";
import { useAuth } from "../lib/auth-context";
import { api, can, type Me } from "../lib/api";
import { Header } from "../components/Header";
import { BillingBanner } from "../components/BillingBanner";
import { TabBar, type TabItem } from "../components/TabBar";
import { DriverDeliveriesScreen } from "./DriverDeliveriesScreen";
import { DispatcherAssignmentsScreen } from "./DispatcherAssignmentsScreen";
import { OrdersTab } from "./orders/OrdersTab";
import { ProspectsTab } from "./prospects/ProspectsTab";
import { ApprovalsScreen } from "./ApprovalsScreen";
import { TodayScreen } from "./TodayScreen";

type TabKey = "orders" | "prospects" | "deliveries" | "assignments" | "approvals" | "today";

const TITLES: Record<TabKey, string> = {
  orders: "Orders",
  prospects: "Prospects",
  deliveries: "My Deliveries",
  assignments: "Assignment Queue",
  approvals: "Approvals",
  today: "Today",
};

/**
 * Which tabs a user gets, from their real capabilities (not the role name),
 * the same way the dashboard's sidebar decides what to show:
 *
 * - salesman:            Orders, Prospects, Today
 * - driver:              Deliveries
 * - dispatcher/warehouse: Assignments
 * - viewer:              Orders (read-only), Today
 * - owner/admin:         Orders, Prospects, Assignments, Approvals, Today
 *
 * Owners hold the driver capability too, but "my deliveries" only means
 * something for drivers, so it's left out for anyone who manages users.
 */
export function tabsFor(me: Me | null): TabKey[] {
  const manager = can(me, "manage_users");
  const driver = can(me, "deliver_order") && !manager;
  const dispatcher = can(me, "dispatch_order");
  const tabs: TabKey[] = [];
  if (can(me, "create_order") || (can(me, "view_orders") && !driver && !dispatcher)) tabs.push("orders");
  if (can(me, "manage_prospects")) tabs.push("prospects");
  if (driver) tabs.push("deliveries");
  if (dispatcher) tabs.push("assignments");
  if (can(me, "resolve_escalation")) tabs.push("approvals");
  if (can(me, "view_reports")) tabs.push("today");
  return tabs;
}

export function HomeScreen() {
  const { me } = useAuth();
  const tabs = useMemo(() => tabsFor(me), [me]);
  const [tab, setTab] = useState<TabKey | null>(tabs[0] ?? null);
  const [approvals, setApprovals] = useState(0);
  const canApprove = tabs.includes("approvals");

  // keep the selected tab valid if capabilities change (e.g. after a refresh)
  useEffect(() => {
    if (!tab || !tabs.includes(tab)) setTab(tabs[0] ?? null);
  }, [tabs, tab]);

  // badge on the Approvals tab
  useEffect(() => {
    if (!canApprove) return;
    api("/orders/escalations/open")
      .then((rows: unknown[]) => setApprovals(rows.length))
      .catch(() => setApprovals(0));
  }, [canApprove]);
  const onApprovalCount = useCallback((n: number) => setApprovals(n), []);

  if (!tab) {
    return (
      <View style={styles.flex}>
        <Header title="Stonic" />
        <BillingBanner />
        <View style={styles.centered}>
          <Text style={styles.noAccessTitle}>Nothing to show yet</Text>
          <Text style={styles.noAccessText}>
            Your account ({me?.role}) has no screens in the mobile app. Ask your admin to check your role on the
            Team & Access page.
          </Text>
        </View>
      </View>
    );
  }

  const items: TabItem<TabKey>[] = tabs.map((key) => ({
    key,
    ...TAB_META[key],
    badge: key === "approvals" ? approvals : undefined,
  }));

  return (
    <View style={styles.flex}>
      <Header title={TITLES[tab]} />
      <BillingBanner />
      <View style={styles.flex}>
        {tab === "orders" && <OrdersTab canCreate={can(me, "create_order")} />}
        {tab === "prospects" && <ProspectsTab />}
        {tab === "deliveries" && <DriverDeliveriesScreen />}
        {tab === "assignments" && <DispatcherAssignmentsScreen />}
        {tab === "approvals" && <ApprovalsScreen onCount={onApprovalCount} />}
        {tab === "today" && <TodayScreen />}
      </View>
      {items.length > 1 && <TabBar tabs={items} active={tab} onChange={setTab} />}
    </View>
  );
}

const TAB_META: Record<TabKey, Omit<TabItem<TabKey>, "key">> = {
  orders: { label: "Orders", icon: ClipboardList },
  prospects: { label: "Prospects", icon: Target },
  deliveries: { label: "Deliveries", icon: Truck },
  assignments: { label: "Assign", icon: Route },
  approvals: { label: "Approvals", icon: ShieldCheck },
  today: { label: "Today", icon: ChartColumn },
};

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  noAccessTitle: { ...typography.heading, color: colors.text },
  noAccessText: { ...typography.body, color: colors.textMuted, textAlign: "center", lineHeight: 22 },
});