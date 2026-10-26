import { useCallback, useEffect, useState } from "react";
import { View, Text, FlatList, RefreshControl, StyleSheet } from "react-native";
import { Check, X } from "lucide-react-native";
import { api } from "../lib/api";
import { useBack } from "../lib/use-back";
import { ago, errorText } from "../lib/format";
import type { Escalation } from "../lib/types";
import { Badge, Button, Card, Empty, ErrorText, Input, Loading, Notice, shared } from "../components/ui";
import { colors, radius, spacing, typography } from "../theme/theme";
import { OrderDetailScreen } from "./orders/OrderDetailScreen";

const REASON: Record<string, string> = {
  insufficient_stock: "Short on stock",
};

/**
 * Orders held for a person to decide (the dashboard's Escalations page).
 * Approve fulfils what stock allows and confirms the order; reject cancels
 * it. Either way the customer is told on WhatsApp.
 */
export function ApprovalsScreen({ onCount }: { onCount?: (n: number) => void }) {
  const [rows, setRows] = useState<Escalation[] | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const closeOrder = useCallback(() => setOpenOrder(null), []);
  useBack(openOrder !== null, closeOrder);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError("");
    try {
      const data: Escalation[] = await api("/orders/escalations/open");
      setRows(data);
      onCount?.(data.length);
    } catch (e) {
      setError(errorText(e, "Failed to load approvals"));
      setRows((r) => r ?? []);
    } finally {
      setRefreshing(false);
    }
  }, [onCount]);

  useEffect(() => {
    load();
  }, [load]);

  if (openOrder) return <OrderDetailScreen id={openOrder} onBack={closeOrder} />;
  if (rows === null) return <Loading />;

  return (
    <FlatList
      style={shared.screen}
      contentContainerStyle={shared.list}
      data={rows}
      keyExtractor={(e) => e.id}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
      keyboardShouldPersistTaps="handled"
      ListHeaderComponent={
        <>
          <ErrorText text={error} />
          <Notice text={msg} />
        </>
      }
      ListEmptyComponent={<Empty text="Nothing waiting for approval." />}
      renderItem={({ item }) => (
        <EscalationCard
          item={item}
          onOpenOrder={item.order_id ? () => setOpenOrder(item.order_id) : undefined}
          onResolved={(text) => {
            setMsg(text);
            load();
          }}
        />
      )}
    />
  );
}

function EscalationCard({
  item,
  onOpenOrder,
  onResolved,
}: {
  item: Escalation;
  onOpenOrder?: () => void;
  onResolved: (msg: string) => void;
}) {
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const order = item.context.order_number;
  const shortfalls = item.context.shortfalls ?? [];

  async function resolve() {
    if (!decision) return;
    setBusy(true);
    setError("");
    try {
      const done: Escalation = await api(`/orders/escalations/${item.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ approve: decision === "approve", note: note.trim() || null }),
      });
      const name = order ?? "The order";
      // approving when nothing at all is in stock cancels the order server-side
      onResolved(
        decision === "reject"
          ? `${name} rejected and cancelled.`
          : done.resolution === "approved"
            ? `${name} approved and confirmed with the stock available.`
            : `${name} was cancelled: none of its items were in stock.`,
      );
    } catch (e) {
      setError(errorText(e, "Failed to resolve"));
      setBusy(false);
    }
  }

  return (
    <Card>
      <View style={shared.between}>
        <Text style={[shared.title, styles.flex]} numberOfLines={1}>{item.customer_name || "Customer"}</Text>
        <Text style={shared.dim}>{ago(item.created_at)}</Text>
      </View>
      <View style={[shared.inline, styles.gap]}>
        <Badge label={REASON[item.reason_type] ?? item.reason_type.replace(/_/g, " ")} tone="warning" />
        {order ? <Text style={shared.meta}>{order}</Text> : null}
      </View>

      {shortfalls.length > 0 && (
        <View style={styles.box}>
          {shortfalls.map((s) => (
            <View key={s.sku} style={shared.between}>
              <Text style={styles.sku}>{s.sku}</Text>
              <Text style={styles.short}>
                {s.available} of {s.requested} in stock
              </Text>
            </View>
          ))}
        </View>
      )}
      {item.ai_recommendation ? <Text style={styles.rec}>{item.ai_recommendation}</Text> : null}
      <ErrorText text={error} />

      {decision === null ? (
        <View style={[shared.inline, styles.actions]}>
          <Button label="Approve" icon={Check} small onPress={() => setDecision("approve")} />
          <Button label="Reject" icon={X} small variant="outline" onPress={() => setDecision("reject")} />
          {onOpenOrder && <Button label="View order" small variant="ghost" onPress={onOpenOrder} />}
        </View>
      ) : (
        <View style={[styles.confirm, decision === "reject" && styles.confirmReject]}>
          <Text style={styles.confirmText}>
            {decision === "approve"
              ? "Confirm the order with the stock available? Short lines are reduced."
              : "Cancel this order? The customer is told on WhatsApp."}
          </Text>
          <Input value={note} onChangeText={setNote} placeholder="Note (optional)" />
          <View style={[shared.inline, styles.actions]}>
            <Button
              label={decision === "approve" ? "Approve" : "Reject order"}
              variant={decision === "approve" ? "primary" : "danger"}
              small
              busy={busy}
              onPress={resolve}
            />
            <Button label="Back" small variant="outline" disabled={busy} onPress={() => setDecision(null)} />
          </View>
        </View>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  gap: { marginTop: 6 },
  box: { marginTop: spacing.sm + 2, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.sm + 2, gap: 4 },
  sku: { ...typography.caption, color: colors.text, fontWeight: "600" },
  short: { ...typography.caption, color: colors.warning, fontWeight: "500" },
  rec: { ...typography.caption, color: colors.textMuted, marginTop: spacing.sm, lineHeight: 18 },
  actions: { marginTop: spacing.sm + 4 },
  confirm: { marginTop: spacing.sm + 4, padding: spacing.sm + 4, borderRadius: radius.md, backgroundColor: colors.accentDim, gap: spacing.sm },
  confirmReject: { backgroundColor: colors.dangerDim },
  confirmText: { ...typography.caption, color: colors.text, fontWeight: "500" },
});