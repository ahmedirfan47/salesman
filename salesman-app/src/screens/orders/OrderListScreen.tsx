import { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, FlatList, Pressable, RefreshControl, ScrollView, StyleSheet } from "react-native";
import { Plus, Search } from "lucide-react-native";
import { api } from "../../lib/api";
import { errorText, money, stamp } from "../../lib/format";
import { orderStatus, type Order } from "../../lib/types";
import { Badge, Button, Card, Chip, Empty, ErrorText, Input, Loading, shared } from "../../components/ui";
import { colors, radius, spacing } from "../../theme/theme";

type Filter = "all" | "review" | "active" | "done" | "cancelled";

const FILTERS: { key: Filter; label: string; statuses?: string[] }[] = [
  { key: "all", label: "All" },
  { key: "review", label: "Needs approval", statuses: ["requires_human_review"] },
  { key: "active", label: "In progress", statuses: ["confirmed", "preparing", "dispatched"] },
  { key: "done", label: "Delivered", statuses: ["delivered", "completed"] },
  { key: "cancelled", label: "Cancelled", statuses: ["cancelled"] },
];

export function OrderListScreen({ onOpen, onNew }: { onOpen: (id: string) => void; onNew?: () => void }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError("");
    try {
      setOrders(await api("/orders"));
    } catch (e) {
      setError(errorText(e, "Failed to load orders"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => {
    const statuses = FILTERS.find((f) => f.key === filter)?.statuses;
    const term = q.trim().toLowerCase();
    return orders.filter((o) => {
      if (statuses && !statuses.includes(o.status)) return false;
      if (!term) return true;
      return [o.order_number, o.customer_name, o.customer_company, o.whatsapp_number]
        .some((v) => v?.toLowerCase().includes(term));
    });
  }, [orders, filter, q]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: orders.length, review: 0, active: 0, done: 0, cancelled: 0 };
    for (const o of orders) {
      for (const f of FILTERS) if (f.statuses?.includes(o.status)) c[f.key] += 1;
    }
    return c;
  }, [orders]);

  if (loading) return <Loading />;

  return (
    <View style={shared.screen}>
      <View style={styles.searchRow}>
        <View style={styles.search}>
          <Search size={16} color={colors.textDim} />
          <Input
            value={q}
            onChangeText={setQ}
            placeholder="Customer or order number"
            style={styles.searchInput}
            autoCorrect={false}
          />
        </View>
        {onNew && <Button label="New" icon={Plus} onPress={onNew} small />}
      </View>
      <View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={shared.chips}>
          {FILTERS.map((f) => (
            <Chip
              key={f.key}
              label={counts[f.key] ? `${f.label} ${counts[f.key]}` : f.label}
              active={filter === f.key}
              onPress={() => setFilter(f.key)}
            />
          ))}
        </ScrollView>
      </View>
      <FlatList
        contentContainerStyle={shared.list}
        data={rows}
        keyExtractor={(o) => o.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
        keyboardShouldPersistTaps="handled"
        ListHeaderComponent={<ErrorText text={error} />}
        ListEmptyComponent={
          <Empty text={orders.length ? "No orders match." : onNew ? "No orders yet. Tap New to take one." : "No orders yet."} />
        }
        renderItem={({ item }) => {
          const s = orderStatus(item.status);
          const units = item.items.reduce((n, i) => n + i.quantity, 0);
          return (
            <Pressable onPress={() => onOpen(item.id)} accessibilityRole="button">
              {({ pressed }) => (
                <Card style={pressed ? styles.pressed : undefined}>
                  <View style={shared.between}>
                    <Text style={[shared.title, styles.flex]} numberOfLines={1}>
                      {item.customer_name || item.customer_company || "Walk-in customer"}
                    </Text>
                    <Text style={styles.total}>{money(item.total_amount, item.currency)}</Text>
                  </View>
                  <View style={[shared.between, styles.second]}>
                    <Text style={shared.meta} numberOfLines={1}>
                      {item.order_number} · {stamp(item.created_at)} · {units} unit{units === 1 ? "" : "s"}
                    </Text>
                    <Badge label={s.label} tone={s.tone} />
                  </View>
                </Card>
              )}
            </Pressable>
          );
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },
  search: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingLeft: spacing.md,
    backgroundColor: colors.surface,
  },
  searchInput: { flex: 1, minWidth: 0, borderWidth: 0, backgroundColor: "transparent", paddingVertical: 9, paddingLeft: 0 },
  total: { fontSize: 15, fontWeight: "700", color: colors.text },
  second: { marginTop: 6 },
  pressed: { backgroundColor: colors.surface },
});