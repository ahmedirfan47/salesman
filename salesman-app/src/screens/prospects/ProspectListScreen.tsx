import { useCallback, useEffect, useState } from "react";
import { View, Text, FlatList, Pressable, RefreshControl, ScrollView, StyleSheet } from "react-native";
import { Plus, RefreshCw, Search } from "lucide-react-native";
import { api } from "../../lib/api";
import { ago, errorText } from "../../lib/format";
import { PRIORITY_TONE, PROSPECT_STATUS, type Prospect } from "../../lib/types";
import { Badge, Button, Card, Chip, Empty, ErrorText, Input, Loading, Notice, shared } from "../../components/ui";
import { colors, radius, spacing, typography } from "../../theme/theme";

const STATUSES = [
  { key: "open", label: "Open" },
  { key: "new", label: "New" },
  { key: "contacted", label: "Contacted" },
  { key: "interested", label: "Interested" },
  { key: "won", label: "Won" },
  { key: "lost", label: "Lost" },
] as const;
type StatusKey = (typeof STATUSES)[number]["key"];
type Kind = "" | "new" | "winback";

export function KindBadge({ kind }: { kind: Prospect["kind"] }) {
  return kind === "winback" ? <Badge label="Win-back" tone="violet" /> : <Badge label="New shop" tone="accent" />;
}

export function ProspectListScreen({ onOpen, onNew }: { onOpen: (id: string) => void; onNew: () => void }) {
  const [rows, setRows] = useState<Prospect[] | null>(null);
  const [status, setStatus] = useState<StatusKey>("open");
  const [kind, setKind] = useState<Kind>("");
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [finding, setFinding] = useState(false);

  // search as you type, without a request per keystroke
  useEffect(() => {
    const t = setTimeout(() => setTerm(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError("");
    const params = [`status=${status}`];
    if (kind) params.push(`kind=${kind}`);
    if (mine) params.push("mine=true");
    if (term) params.push(`q=${encodeURIComponent(term)}`);
    try {
      setRows(await api(`/prospects?${params.join("&")}`));
    } catch (e) {
      setError(errorText(e, "Failed to load prospects"));
      setRows((r) => r ?? []);
    } finally {
      setRefreshing(false);
    }
  }, [status, kind, mine, term]);

  useEffect(() => {
    load();
  }, [load]);

  async function findWinbacks() {
    setFinding(true);
    setError("");
    setMsg("");
    try {
      const r: { created: number; closed: number } = await api("/prospects/winback/refresh", { method: "POST" });
      setMsg(
        r.created || r.closed
          ? `${r.created} customer${r.created === 1 ? "" : "s"} added for win-back${r.closed ? `, ${r.closed} closed as won (they ordered again)` : ""}.`
          : "No new win-backs. Every quiet customer is already on the list.",
      );
      await load();
    } catch (e) {
      setError(errorText(e, "Failed to look for win-backs"));
    } finally {
      setFinding(false);
    }
  }

  return (
    <View style={shared.screen}>
      <View style={styles.searchRow}>
        <View style={styles.search}>
          <Search size={16} color={colors.textDim} />
          <Input value={q} onChangeText={setQ} placeholder="Shop, area or phone" style={styles.searchInput} autoCorrect={false} />
        </View>
        <Button label="Add" icon={Plus} onPress={onNew} small />
      </View>
      <View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={shared.chips}>
          {STATUSES.map((s) => (
            <Chip key={s.key} label={s.label} active={status === s.key} onPress={() => setStatus(s.key)} />
          ))}
        </ScrollView>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[shared.chips, styles.secondChips]}>
          <Chip label="All kinds" active={kind === ""} onPress={() => setKind("")} />
          <Chip label="New shops" active={kind === "new"} onPress={() => setKind("new")} />
          <Chip label="Win-back" active={kind === "winback"} onPress={() => setKind("winback")} />
          <Chip label="Assigned to me" active={mine} onPress={() => setMine((m) => !m)} />
        </ScrollView>
      </View>
      {rows === null ? (
        <Loading />
      ) : (
        <FlatList
          contentContainerStyle={shared.list}
          data={rows}
          keyExtractor={(p) => p.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
          keyboardShouldPersistTaps="handled"
          ListHeaderComponent={
            <>
              <ErrorText text={error} />
              <Notice text={msg} />
            </>
          }
          ListEmptyComponent={<Empty text="No prospects here. Add a shop, or look for customers who stopped ordering." />}
          ListFooterComponent={
            kind !== "new" ? (
              <Button
                label="Find customers to win back"
                icon={RefreshCw}
                variant="outline"
                onPress={findWinbacks}
                busy={finding}
                style={styles.footerButton}
              />
            ) : null
          }
          renderItem={({ item }) => {
            const s = PROSPECT_STATUS[item.status];
            const where = [item.area, item.zone_name].filter(Boolean).join(" · ");
            return (
              <Pressable onPress={() => onOpen(item.id)} accessibilityRole="button">
                {({ pressed }) => (
                  <Card style={pressed ? styles.pressed : undefined}>
                    <View style={shared.between}>
                      <Text style={[shared.title, styles.flex]} numberOfLines={1}>{item.name}</Text>
                      <Text style={[styles.priority, { color: priorityColor(item.priority) }]}>{item.priority}</Text>
                    </View>
                    <View style={[shared.inline, styles.badges]}>
                      <KindBadge kind={item.kind} />
                      <Badge label={s.label} tone={s.tone} />
                    </View>
                    {item.insight ? <Text style={styles.insight} numberOfLines={2}>{item.insight}</Text> : null}
                    <Text style={shared.dim} numberOfLines={1}>
                      {[where, item.assigned_to_name, item.last_contacted_at ? `contacted ${ago(item.last_contacted_at)}` : "not contacted yet"]
                        .filter(Boolean)
                        .join(" · ")}
                    </Text>
                  </Card>
                )}
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}

function priorityColor(p: Prospect["priority"]): string {
  const tone = PRIORITY_TONE[p];
  return tone === "success" ? colors.success : tone === "warning" ? colors.warning : colors.textDim;
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  searchRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingTop: spacing.md },
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
  secondChips: { paddingTop: 0 },
  badges: { marginTop: 6, marginBottom: 6 },
  priority: { ...typography.tiny, textTransform: "uppercase" },
  insight: { ...typography.caption, color: colors.textMuted, marginBottom: 4, lineHeight: 18 },
  pressed: { backgroundColor: colors.surface },
  footerButton: { marginTop: spacing.md },
});