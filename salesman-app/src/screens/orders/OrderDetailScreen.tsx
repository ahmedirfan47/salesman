import { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, RefreshControl, Linking, StyleSheet } from "react-native";
import { MessageCircle } from "lucide-react-native";
import { api } from "../../lib/api";
import { digits, errorText, money, stamp } from "../../lib/format";
import { orderStatus, type OrderDetail } from "../../lib/types";
import { BackBar, Badge, Button, Card, ErrorText, Loading, Notice, SectionTitle, shared } from "../../components/ui";
import { colors, spacing, typography } from "../../theme/theme";

export function OrderDetailScreen({ id, notice, onBack }: { id: string; notice?: string; onBack: () => void }) {
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError("");
    try {
      setOrder(await api(`/orders/${id}`));
    } catch (e) {
      setError(errorText(e, "Failed to load the order"));
    } finally {
      setRefreshing(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!order) {
    return (
      <View style={shared.screen}>
        <BackBar title="Order" onBack={onBack} />
        {error ? <View style={shared.list}><ErrorText text={error} /></View> : <Loading />}
      </View>
    );
  }

  const s = orderStatus(order.status);
  const phone = digits(order.whatsapp_number);
  const short = order.items.filter((i) => i.available_at_order !== null && i.available_at_order < i.quantity);

  return (
    <View style={shared.screen}>
      <BackBar title={order.order_number} onBack={onBack} />
      <ScrollView
        contentContainerStyle={shared.list}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
      >
        {notice && !(order.status === "requires_human_review" && short.length > 0) ? (
          <Notice text={notice} tone={order.status === "requires_human_review" ? "warning" : "success"} />
        ) : null}
        <ErrorText text={error} />

        <Card>
          <View style={shared.between}>
            <Badge label={s.label} tone={s.tone} />
            <Text style={shared.dim}>{stamp(order.created_at)}</Text>
          </View>
          <Text style={styles.customer}>{order.customer_name || "Walk-in customer"}</Text>
          {order.customer_company && order.customer_company !== order.customer_name ? (
            <Text style={shared.meta}>{order.customer_company}</Text>
          ) : null}
          {order.whatsapp_number ? <Text style={shared.meta}>{order.whatsapp_number}</Text> : null}
          {phone ? (
            <Button
              label="WhatsApp customer"
              icon={MessageCircle}
              variant="whatsapp"
              small
              style={styles.wa}
              onPress={() => Linking.openURL(`https://wa.me/${phone}`)}
            />
          ) : null}
        </Card>

        {order.status === "requires_human_review" && short.length > 0 && (
          <Notice
            tone="warning"
            text={`Waiting for a manager: ${short.map((i) => `${i.product_name} (${i.available_at_order} of ${i.quantity} in stock)`).join(", ")}.`}
          />
        )}

        <SectionTitle>ITEMS</SectionTitle>
        <Card>
          {order.items.map((item, idx) => (
            <View key={item.id} style={[styles.line, idx > 0 && styles.lineBorder]}>
              <View style={styles.flex}>
                <Text style={styles.product}>{item.product_name}</Text>
                <Text style={shared.dim}>
                  {item.sku} · {item.quantity} × {money(item.unit_price)}
                </Text>
              </View>
              <Text style={styles.amount}>{money(item.line_total)}</Text>
            </View>
          ))}
          <View style={[styles.line, styles.lineBorder]}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.total}>{money(order.total_amount, order.currency)}</Text>
          </View>
        </Card>

        {order.events.length > 0 && (
          <>
            <SectionTitle>HISTORY</SectionTitle>
            <Card>
              {order.events.map((e, idx) => (
                <View key={`${e.created_at}-${idx}`} style={[styles.event, idx > 0 && styles.lineBorder]}>
                  <View style={shared.between}>
                    <Text style={styles.product}>{orderStatus(e.to_status).label}</Text>
                    <Text style={shared.dim}>{stamp(e.created_at)}</Text>
                  </View>
                  {e.actor_name ? <Text style={shared.dim}>{e.actor_name}</Text> : null}
                  {e.note ? <Text style={shared.meta}>{e.note}</Text> : null}
                </View>
              ))}
            </Card>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  customer: { ...typography.heading, color: colors.text, marginTop: spacing.sm + 4 },
  wa: { alignSelf: "flex-start", marginTop: spacing.sm + 4 },
  line: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm + 2 },
  lineBorder: { borderTopWidth: 1, borderTopColor: colors.border },
  product: { ...typography.caption, color: colors.text, fontWeight: "600" },
  amount: { ...typography.caption, color: colors.text, fontWeight: "500" },
  totalLabel: { ...typography.bodyMedium, color: colors.text, flex: 1 },
  total: { fontSize: 17, fontWeight: "700", color: colors.text },
  event: { paddingVertical: spacing.sm },
});