import { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, Pressable, RefreshControl, StyleSheet } from "react-native";
import { ChevronLeft, ChevronRight } from "lucide-react-native";
import { api } from "../lib/api";
import { day, errorText, isoDate, money } from "../lib/format";
import { orderStatus, type DailySummary } from "../lib/types";
import { Badge, Card, Empty, ErrorText, Loading, Notice, SectionTitle, shared } from "../components/ui";
import { colors, radius, spacing, typography } from "../theme/theme";

const LOW_STOCK = 10;

/** The day at a glance -- same numbers as the dashboard's daily report. */
export function TodayScreen() {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<DailySummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const date = isoDate(offset);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError("");
    try {
      setData(await api(`/reports/daily/summary?day=${date}`));
    } catch (e) {
      setError(errorText(e, "Failed to load the report"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [date]);

  useEffect(() => {
    load();
  }, [load]);

  const t = data?.totals;
  const cur = data?.currency ?? "";
  const top = [...(data?.products_sold ?? [])].sort((a, b) => b.revenue - a.revenue).slice(0, 5);
  const low = [...(data?.remaining_stock ?? [])].filter((s) => s.quantity <= LOW_STOCK).sort((a, b) => a.quantity - b.quantity).slice(0, 8);

  return (
    <View style={shared.screen}>
      <View style={styles.dateBar}>
        <Pressable onPress={() => setOffset((o) => o - 1)} hitSlop={10} accessibilityLabel="Previous day" style={styles.arrow}>
          <ChevronLeft size={22} color={colors.accent} />
        </Pressable>
        <Text style={styles.date}>{offset === 0 ? "Today" : offset === -1 ? "Yesterday" : day(date)}</Text>
        <Pressable
          onPress={() => setOffset((o) => Math.min(0, o + 1))}
          hitSlop={10}
          disabled={offset === 0}
          accessibilityLabel="Next day"
          style={[styles.arrow, offset === 0 && styles.off]}
        >
          <ChevronRight size={22} color={colors.accent} />
        </Pressable>
      </View>

      {loading && !data ? (
        <Loading />
      ) : (
        <ScrollView
          contentContainerStyle={shared.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
        >
          <ErrorText text={error} />
          {t && (
            <>
              <View style={styles.tiles}>
                <Tile label="Revenue" value={money(t.total_revenue, cur)} wide />
                <Tile label="Orders" value={String(t.total_orders)} />
                <Tile label="Average order" value={money(t.avg_order_value)} />
                <Tile label="Units sold" value={String(t.total_units_sold)} />
                <Tile label="Cancelled" value={String(t.cancelled_orders)} />
              </View>
              {t.review_orders > 0 && (
                <Notice
                  tone="warning"
                  text={`${t.review_orders} order${t.review_orders === 1 ? " is" : "s are"} waiting for approval.`}
                />
              )}

              <SectionTitle>TOP PRODUCTS</SectionTitle>
              {top.length === 0 ? (
                <Empty text="Nothing sold on this day." />
              ) : (
                <Card>
                  {top.map((p, i) => (
                    <View key={p.sku} style={[styles.line, i > 0 && styles.border]}>
                      <View style={styles.flex}>
                        <Text style={styles.name} numberOfLines={1}>{p.name}</Text>
                        <Text style={shared.dim}>{p.qty} sold</Text>
                      </View>
                      <Text style={styles.amount}>{money(p.revenue)}</Text>
                    </View>
                  ))}
                </Card>
              )}

              {low.length > 0 && (
                <>
                  <SectionTitle>LOW STOCK</SectionTitle>
                  <Card>
                    {low.map((s, i) => (
                      <View key={s.sku} style={[styles.line, i > 0 && styles.border]}>
                        <Text style={[styles.name, styles.flex]} numberOfLines={1}>{s.name}</Text>
                        <Badge label={s.quantity <= 0 ? "Out" : `${s.quantity} left`} tone={s.quantity <= 0 ? "danger" : "warning"} />
                      </View>
                    ))}
                  </Card>
                </>
              )}

              <SectionTitle>ORDERS ({data.orders.length})</SectionTitle>
              {data.orders.length === 0 ? (
                <Empty text="No orders on this day." />
              ) : (
                <Card>
                  {data.orders.map((o, i) => {
                    const s = orderStatus(o.status);
                    return (
                      <View key={o.order_number} style={[styles.line, i > 0 && styles.border]}>
                        <View style={styles.flex}>
                          <Text style={styles.name} numberOfLines={1}>{o.customer || "Walk-in customer"}</Text>
                          <Text style={shared.dim}>{o.order_number} · {o.time}</Text>
                        </View>
                        <View style={styles.right}>
                          <Text style={styles.amount}>{money(o.total)}</Text>
                          <Badge label={s.label} tone={s.tone} />
                        </View>
                      </View>
                    );
                  })}
                </Card>
              )}
            </>
          )}
        </ScrollView>
      )}
    </View>
  );
}

function Tile({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <View style={[styles.tile, wide && styles.tileWide]}>
      <Text style={styles.tileLabel}>{label}</Text>
      <Text style={[styles.tileValue, wide && styles.tileValueWide]} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  off: { opacity: 0.3 },
  dateBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  arrow: { padding: 4 },
  date: { ...typography.bodyMedium, fontWeight: "600", color: colors.text },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.sm },
  tile: {
    flexBasis: "47%",
    flexGrow: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  tileWide: { flexBasis: "100%", backgroundColor: colors.accentDim },
  tileLabel: { ...typography.caption, color: colors.textMuted },
  tileValue: { fontSize: 20, fontWeight: "700", color: colors.text, marginTop: 4 },
  tileValueWide: { fontSize: 26, color: colors.accent },
  line: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm + 2 },
  border: { borderTopWidth: 1, borderTopColor: colors.border },
  name: { ...typography.caption, color: colors.text, fontWeight: "600" },
  amount: { ...typography.caption, color: colors.text, fontWeight: "600" },
  right: { alignItems: "flex-end", gap: 4 },
});