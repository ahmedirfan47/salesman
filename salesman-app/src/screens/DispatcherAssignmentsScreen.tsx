import { useEffect, useState } from "react";
import {
  View,
  Text,
  FlatList,
  Pressable,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { api } from "../lib/api";

type Order = { id: string; order_number: string; customer_name: string | null; total_amount: string; currency: string };
type Zone = { id: string; name: string };
type Choice = { zoneId?: string; driverId?: string; driverName?: string };

/**
 * Mirrors the web dashboard's Assignment Queue -- same endpoints
 * (GET /orders, GET /zones, GET /zones/suggest-driver/{id},
 * POST /zones/assign/{orderId}). React Native has no native <select>, so a
 * zone is picked via a row of tappable chips instead of a dropdown.
 */
export function DispatcherAssignmentsScreen() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [zones, setZones] = useState<Zone[]>([]);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load(isRefresh = false) {
    if (isRefresh) setRefreshing(true);
    setError("");
    try {
      const [allOrders, allZones] = await Promise.all([api("/orders"), api("/zones")]);
      setOrders(allOrders.filter((o: any) => o.status === "confirmed"));
      setZones(allZones);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function pickZone(orderId: string, zoneId: string) {
    setChoices((c) => ({ ...c, [orderId]: { zoneId } }));
    try {
      const s = await api(`/zones/suggest-driver/${zoneId}`);
      setChoices((c) => ({
        ...c,
        [orderId]: { zoneId, driverId: s.driver_id ?? undefined, driverName: s.driver_name ?? undefined },
      }));
    } catch {
      // leave zone selected even if suggestion fails; dispatcher sees "no driver"
    }
  }

  async function assign(orderId: string, alsoDispatch: boolean) {
    const choice = choices[orderId];
    if (!choice?.zoneId || !choice?.driverId) {
      setError("Pick a zone with a covering driver first.");
      return;
    }
    setBusyId(orderId);
    setError("");
    try {
      await api(`/zones/assign/${orderId}`, {
        method: "POST",
        body: JSON.stringify({ zone_id: choice.zoneId, driver_id: choice.driverId }),
      });
      if (alsoDispatch) {
        await api(`/orders/${orderId}/transition`, {
          method: "POST",
          body: JSON.stringify({ to_status: "dispatched" }),
        });
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to assign");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <FlatList
      contentContainerStyle={styles.list}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
      data={orders}
      keyExtractor={(o) => o.id}
      ListHeaderComponent={error ? <Text style={styles.error}>{error}</Text> : null}
      ListEmptyComponent={
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>Nothing waiting to assign.</Text>
        </View>
      }
      renderItem={({ item: order }) => {
        const choice = choices[order.id] || {};
        return (
          <View style={styles.card}>
            <Text style={styles.orderNumber}>{order.order_number}</Text>
            <Text style={styles.customer}>{order.customer_name ?? "—"}</Text>
            <Text style={styles.meta}>
              {order.currency} {Number(order.total_amount).toLocaleString()}
            </Text>

            <Text style={styles.label}>Zone</Text>
            <View style={styles.chipRow}>
              {zones.map((z) => {
                const active = choice.zoneId === z.id;
                return (
                  <Pressable
                    key={z.id}
                    onPress={() => pickZone(order.id, z.id)}
                    style={[styles.chip, active && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>{z.name}</Text>
                  </Pressable>
                );
              })}
            </View>

            {choice.zoneId && (
              <Text style={styles.suggestion}>
                {choice.driverName ? `Suggested: ${choice.driverName}` : "No driver covers this zone"}
              </Text>
            )}

            <View style={styles.actionRow}>
              <Pressable
                style={[styles.outlineButton, (!choice.driverId || busyId === order.id) && styles.buttonDisabled]}
                disabled={!choice.driverId || busyId === order.id}
                onPress={() => assign(order.id, false)}
              >
                <Text style={styles.outlineButtonText}>Assign</Text>
              </Pressable>
              <Pressable
                style={[styles.button, (!choice.driverId || busyId === order.id) && styles.buttonDisabled]}
                disabled={!choice.driverId || busyId === order.id}
                onPress={() => assign(order.id, true)}
              >
                <Text style={styles.buttonText}>
                  {busyId === order.id ? "Working…" : "Assign & Dispatch"}
                </Text>
              </Pressable>
            </View>
          </View>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg },
  list: { padding: spacing.lg, backgroundColor: colors.bg, flexGrow: 1 },
  error: { ...typography.caption, color: "#DC2626", marginBottom: spacing.sm },
  card: {
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  orderNumber: { ...typography.caption, color: colors.textDim, fontFamily: "monospace" },
  customer: { ...typography.bodyMedium, color: colors.text, marginTop: 2 },
  meta: { ...typography.caption, color: colors.textMuted, marginTop: 2, marginBottom: spacing.sm },
  label: { ...typography.tiny, color: colors.textMuted, marginBottom: spacing.xs },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginRight: spacing.xs,
    marginBottom: spacing.xs,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { ...typography.caption, color: colors.textMuted },
  chipTextActive: { color: colors.white, fontWeight: "600" },
  suggestion: { ...typography.caption, color: colors.text, marginTop: spacing.sm },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  outlineButton: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.pill,
    paddingVertical: 10,
    alignItems: "center",
  },
  outlineButtonText: { ...typography.caption, color: colors.text, fontWeight: "600" },
  button: {
    flex: 1,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 10,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { ...typography.caption, color: colors.white, fontWeight: "600" },
  emptyCard: { padding: spacing.xl, alignItems: "center", backgroundColor: colors.surface, borderRadius: radius.lg },
  emptyText: { ...typography.body, color: colors.textDim },
});