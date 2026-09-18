import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  FlatList,
  Pressable,
  StyleSheet,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { api } from "../lib/api";

type Order = {
  id: string;
  order_number: string;
  status: string;
  customer_name: string | null;
  total_amount: string;
  currency: string;
};

/**
 * Mirrors the web dashboard's /deliveries page -- same endpoint
 * (GET /zones/my-deliveries/list), same "to deliver" vs "delivered" split,
 * same transition call to mark an order delivered.
 */
export function DriverDeliveriesScreen() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError("");
    try {
      const data = await api("/zones/my-deliveries/list");
      setOrders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load deliveries");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Re-fetch on mount. Pull-to-refresh (below) covers returning to this
  // screen after backgrounding the app -- no navigation library is used
  // here, so there's no "screen focus" event to hook into.
  useEffect(() => {
    load();
  }, [load]);

  async function markDelivered(id: string) {
    setBusyId(id);
    try {
      await api(`/orders/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_status: "delivered" }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update order");
    } finally {
      setBusyId(null);
    }
  }

  const active = orders.filter((o) => o.status === "dispatched");
  const done = orders.filter((o) => o.status === "delivered");

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
      data={active}
      keyExtractor={(o) => o.id}
      ListHeaderComponent={
        <>
          <Text style={styles.sectionTitle}>TO DELIVER ({active.length})</Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </>
      }
      renderItem={({ item }) => (
        <View style={styles.card}>
          <View style={{ flex: 1 }}>
            <Text style={styles.customer}>{item.customer_name ?? "—"}</Text>
            <Text style={styles.meta}>
              {item.order_number} · {item.currency} {Number(item.total_amount).toLocaleString()}
            </Text>
          </View>
          <Pressable
            style={[styles.button, busyId === item.id && styles.buttonDisabled]}
            onPress={() => markDelivered(item.id)}
            disabled={busyId === item.id}
          >
            <Text style={styles.buttonText}>
              {busyId === item.id ? "Updating…" : "Mark Delivered"}
            </Text>
          </Pressable>
        </View>
      )}
      ListEmptyComponent={
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>No active deliveries right now.</Text>
        </View>
      }
      ListFooterComponent={
        done.length > 0 ? (
          <View>
            <Text style={styles.sectionTitle}>DELIVERED ({done.length})</Text>
            {done.map((o) => (
              <View key={o.id} style={styles.doneRow}>
                <Text style={styles.doneText}>
                  {o.customer_name ?? "—"} · {o.order_number}
                </Text>
                <View style={styles.doneBadge}>
                  <Text style={styles.doneBadgeText}>delivered</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null
      }
    />
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg },
  list: { padding: spacing.lg, backgroundColor: colors.bg, flexGrow: 1 },
  sectionTitle: { ...typography.tiny, color: colors.textMuted, marginBottom: spacing.sm, marginTop: spacing.md },
  error: { ...typography.caption, color: "#DC2626", marginBottom: spacing.sm },
  card: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    gap: spacing.sm,
  },
  customer: { ...typography.bodyMedium, color: colors.text },
  meta: { ...typography.caption, color: colors.textMuted, marginTop: 2 },
  button: {
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { ...typography.caption, color: colors.white, fontWeight: "600" },
  emptyCard: {
    padding: spacing.xl,
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
  },
  emptyText: { ...typography.body, color: colors.textDim },
  doneRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  doneText: { ...typography.body, color: colors.textMuted, flex: 1 },
  doneBadge: { backgroundColor: colors.accentDim, borderRadius: radius.sm, paddingHorizontal: 8, paddingVertical: 2 },
  doneBadgeText: { ...typography.tiny, color: colors.accent },
});