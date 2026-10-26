import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  Linking,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
} from "react-native";
import {
  ExternalLink, MapPin, MessageCircle, Pencil, Phone, Sparkles, StickyNote, Trophy, User, CircleX,
} from "lucide-react-native";
import { api } from "../../lib/api";
import { ago, errorText } from "../../lib/format";
import { PROSPECT_STATUS, type ProspectDetail, type Zone } from "../../lib/types";
import {
  BackBar, Badge, Button, Card, Chip, ErrorText, Input, Loading, Notice, SectionTitle, shared,
} from "../../components/ui";
import { colors, radius, spacing, typography } from "../../theme/theme";
import { KindBadge } from "./ProspectListScreen";

const ACTIVITY_LABEL: Record<string, string> = {
  created: "Added", note: "Note", contacted: "WhatsApp opened", status: "Status", won: "Won",
};

type Form = { name: string; phone: string; contact_name: string; area: string; address: string };

/**
 * One prospect, same actions as the dashboard's prospect panel: draft a
 * WhatsApp message with AI (prices checked server-side), open it in
 * WhatsApp, move the status, close as won or lost, and keep notes.
 */
export function ProspectDetailScreen({ id, onBack }: { id: string; onBack: () => void }) {
  const [p, setP] = useState<ProspectDetail | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [message, setMessage] = useState("");
  const [source, setSource] = useState<"ai" | "template" | null>(null);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Form>({ name: "", phone: "", contact_name: "", area: "", address: "" });
  const [showWon, setShowWon] = useState(false);
  const [winZone, setWinZone] = useState<string | null>(null);
  const [showLost, setShowLost] = useState(false);
  const [lostReason, setLostReason] = useState("");

  const apply = useCallback((d: ProspectDetail) => {
    setP(d);
    setForm({
      name: d.name, phone: d.phone ?? "", contact_name: d.contact_name ?? "", area: d.area ?? "", address: d.address ?? "",
    });
    setWinZone(d.zone_id);
  }, []);

  useEffect(() => {
    api(`/prospects/${id}`).then(apply).catch((e) => setError(errorText(e, "Failed to load")));
    api("/zones").then(setZones).catch(() => setZones([]));
  }, [id, apply]);

  async function run(label: string, fn: () => Promise<ProspectDetail | void>): Promise<boolean> {
    setBusy(label);
    setError("");
    try {
      const d = await fn();
      if (d) apply(d);
      return true;
    } catch (e) {
      setError(errorText(e, "Failed"));
      return false;
    } finally {
      setBusy("");
    }
  }

  const patch = (body: Record<string, unknown>) =>
    run("save", () => api(`/prospects/${id}`, { method: "PATCH", body: JSON.stringify(body) }));

  async function draft() {
    setBusy("draft");
    setError("");
    try {
      const d = await api(`/prospects/${id}/draft`, { method: "POST", body: JSON.stringify({ language }) });
      setMessage(d.message);
      setSource(d.source);
    } catch (e) {
      setError(errorText(e, "Failed to draft"));
    } finally {
      setBusy("");
    }
  }

  async function openWhatsApp() {
    if (!p?.phone_digits) return;
    const text = message.trim();
    const url = `https://wa.me/${p.phone_digits}${text ? `?text=${encodeURIComponent(text)}` : ""}`;
    try {
      await Linking.openURL(url);
    } catch {
      setError("Couldn't open WhatsApp on this phone.");
      return;
    }
    run("contacted", () =>
      api(`/prospects/${id}/contacted`, { method: "POST", body: JSON.stringify({ message: text || null }) }),
    );
  }

  if (!p) {
    return (
      <View style={shared.screen}>
        <BackBar title="Prospect" onBack={onBack} />
        {error ? <View style={shared.list}><ErrorText text={error} /></View> : <Loading />}
      </View>
    );
  }

  const closed = p.status === "won" || p.status === "lost";
  const s = PROSPECT_STATUS[p.status];
  const where = [p.address, p.area, p.zone_name].filter(Boolean).join(" · ");
  const working = busy !== "";
  const reasons = p.priority_reasons.filter((r) => r !== p.insight);

  return (
    <KeyboardAvoidingView style={shared.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <BackBar title={p.name} onBack={onBack} />
      <ScrollView contentContainerStyle={shared.list} keyboardShouldPersistTaps="handled">
        <ErrorText text={error} />

        {/* summary */}
        <Card>
          <View style={shared.inline}>
            <KindBadge kind={p.kind} />
            <Badge label={s.label} tone={s.tone} />
            <Text style={styles.priority}>{p.priority} priority</Text>
          </View>
          <Text style={styles.name}>{p.name}</Text>
          {p.insight ? <Text style={styles.insight}>{p.insight}</Text> : null}
          {reasons.length > 0 && (
            <View style={styles.reasons}>
              {reasons.map((r) => (
                <Text key={r} style={styles.reason}>• {r}</Text>
              ))}
            </View>
          )}
        </Card>

        {/* contact details */}
        <SectionTitle>CONTACT</SectionTitle>
        {!editing ? (
          <Card>
            <Detail icon={<Phone size={15} color={colors.textDim} />} text={p.phone ?? "No phone number"} dim={!p.phone} />
            {p.contact_name ? <Detail icon={<User size={15} color={colors.textDim} />} text={p.contact_name} /> : null}
            <Detail icon={<MapPin size={15} color={colors.textDim} />} text={where || "No address"} dim={!where} />
            <View style={[shared.inline, styles.gapTop]}>
              {p.phone_digits ? (
                <Button label="Call" icon={Phone} variant="outline" small onPress={() => Linking.openURL(`tel:+${p.phone_digits}`)} />
              ) : null}
              {p.google_maps_uri ? (
                <Button label="Map" icon={ExternalLink} variant="outline" small onPress={() => Linking.openURL(p.google_maps_uri!)} />
              ) : null}
              {!closed && <Button label="Edit" icon={Pencil} variant="ghost" small onPress={() => setEditing(true)} />}
            </View>
          </Card>
        ) : (
          <Card>
            <Input value={form.name} onChangeText={(v) => setForm({ ...form, name: v })} placeholder="Shop name" />
            <Input value={form.phone} onChangeText={(v) => setForm({ ...form, phone: v })} placeholder="Phone (05…)" keyboardType="phone-pad" style={styles.gapTop} />
            <Input value={form.contact_name} onChangeText={(v) => setForm({ ...form, contact_name: v })} placeholder="Contact person" style={styles.gapTop} />
            <Input value={form.area} onChangeText={(v) => setForm({ ...form, area: v })} placeholder="Area / district" style={styles.gapTop} />
            <Input value={form.address} onChangeText={(v) => setForm({ ...form, address: v })} placeholder="Address" style={styles.gapTop} />
            <View style={[shared.inline, styles.gapTopLg]}>
              <Button
                label="Save"
                small
                busy={busy === "save"}
                disabled={working || !form.name.trim()}
                onPress={async () => {
                  const ok = await patch({
                    name: form.name, phone: form.phone || null, contact_name: form.contact_name || null,
                    area: form.area || null, address: form.address || null,
                  });
                  if (ok) setEditing(false);
                }}
              />
              <Button
                label="Cancel"
                variant="outline"
                small
                onPress={() => {
                  apply(p);
                  setEditing(false);
                }}
              />
            </View>
          </Card>
        )}

        {/* WhatsApp message */}
        {!closed && (
          <>
            <SectionTitle>WHATSAPP MESSAGE</SectionTitle>
            <Card>
              <View style={shared.between}>
                <View style={styles.lang}>
                  {(["en", "ar"] as const).map((l) => (
                    <Pressable
                      key={l}
                      onPress={() => setLanguage(l)}
                      style={[styles.langBtn, language === l && styles.langBtnOn]}
                      accessibilityRole="button"
                      accessibilityState={{ selected: language === l }}
                    >
                      <Text style={[styles.langText, language === l && styles.langTextOn]}>{l === "en" ? "English" : "العربية"}</Text>
                    </Pressable>
                  ))}
                </View>
                <Button
                  label={busy === "draft" ? "Drafting…" : message ? "Redraft" : "Draft with AI"}
                  icon={Sparkles}
                  variant="outline"
                  small
                  disabled={working}
                  onPress={draft}
                />
              </View>
              <Input
                value={message}
                onChangeText={setMessage}
                multiline
                placeholder="Draft a message with AI, or write your own."
                textAlign={language === "ar" ? "right" : "left"}
                style={styles.message}
              />
              {source && (
                <Text style={[shared.dim, styles.gapTop]}>
                  {source === "ai"
                    ? "AI draft. Every price was checked against today's price list. Review before sending."
                    : "Standard message. The AI was unavailable or its draft didn't pass the price check."}
                </Text>
              )}
              <Button
                label="Open in WhatsApp"
                icon={MessageCircle}
                variant="whatsapp"
                disabled={!p.phone_digits || working}
                busy={busy === "contacted"}
                onPress={openWhatsApp}
                style={styles.gapTopLg}
              />
              {!p.phone_digits && <Text style={styles.warn}>Add a phone number to message this shop.</Text>}
            </Card>
          </>
        )}

        {/* status */}
        <SectionTitle>STATUS</SectionTitle>
        <Card>
          {p.status === "won" ? (
            <Text style={styles.won}>Won{p.closed_at ? ` · ${ago(p.closed_at)}` : ""}</Text>
          ) : (
            <View style={shared.inline}>
              {(["new", "contacted", "interested"] as const).map((st) => (
                <Chip
                  key={st}
                  label={PROSPECT_STATUS[st].label}
                  active={p.status === st}
                  onPress={() => p.status !== st && !working && patch({ status: st })}
                />
              ))}
              {p.status === "lost" && <Chip label="Lost" active onPress={() => {}} />}
            </View>
          )}
          {p.status === "lost" && p.lost_reason ? <Text style={styles.lostText}>Lost: {p.lost_reason}</Text> : null}

          {!closed && !showWon && !showLost && (
            <View style={[shared.inline, styles.gapTopLg]}>
              <Button
                label={p.kind === "new" ? "Won: add as customer" : "Mark as won back"}
                icon={Trophy}
                variant="outline"
                small
                disabled={working}
                onPress={() => (p.kind === "new" && zones.length > 0 ? setShowWon(true) : run("won", () => convert(id, winZone)))}
              />
              <Button label="Lost" icon={CircleX} variant="ghost" small disabled={working} onPress={() => setShowLost(true)} />
            </View>
          )}

          {showWon && (
            <View style={styles.panel}>
              <Text style={styles.panelTitle}>Delivery zone for the new customer</Text>
              <View style={shared.inline}>
                <Chip label="No zone" active={winZone === null} onPress={() => setWinZone(null)} />
                {zones.map((z) => (
                  <Chip key={z.id} label={z.name} active={winZone === z.id} onPress={() => setWinZone(z.id)} />
                ))}
              </View>
              <View style={[shared.inline, styles.gapTopLg]}>
                <Button
                  label="Add as customer"
                  small
                  busy={busy === "won"}
                  onPress={async () => {
                    if (await run("won", () => convert(id, winZone))) setShowWon(false);
                  }}
                />
                <Button label="Cancel" variant="outline" small onPress={() => setShowWon(false)} />
              </View>
            </View>
          )}

          {showLost && (
            <View style={[styles.panel, styles.lostPanel]}>
              <Text style={[styles.panelTitle, { color: colors.danger }]}>Why was it lost? (optional)</Text>
              <Input value={lostReason} onChangeText={setLostReason} placeholder="e.g. Has a fixed supplier" />
              <View style={[shared.inline, styles.gapTopLg]}>
                <Button
                  label="Mark lost"
                  variant="danger"
                  small
                  busy={busy === "save"}
                  onPress={async () => {
                    if (await patch({ status: "lost", lost_reason: lostReason.trim() || null })) {
                      setShowLost(false);
                      setLostReason("");
                    }
                  }}
                />
                <Button label="Cancel" variant="outline" small onPress={() => setShowLost(false)} />
              </View>
            </View>
          )}
        </Card>

        {/* notes and history */}
        <SectionTitle>NOTES AND HISTORY</SectionTitle>
        <Card>
          <View style={styles.noteRow}>
            <Input
              value={note}
              onChangeText={setNote}
              placeholder="Add a note, e.g. call back after Asr"
              style={styles.flex}
            />
            <Button
              label="Add"
              icon={StickyNote}
              variant="outline"
              small
              disabled={!note.trim() || working}
              busy={busy === "note"}
              onPress={async () => {
                const ok = await run("note", () =>
                  api(`/prospects/${id}/notes`, { method: "POST", body: JSON.stringify({ text: note.trim() }) }),
                );
                if (ok) setNote("");
              }}
            />
          </View>
          {p.activities.map((a) => (
            <View key={a.id} style={styles.activity}>
              <Text style={shared.dim}>
                <Text style={styles.activityKind}>{ACTIVITY_LABEL[a.kind] ?? a.kind}</Text>
                {a.actor_name ? ` · ${a.actor_name}` : ""} · {ago(a.created_at)}
              </Text>
              {a.body ? <Text style={styles.activityBody}>{a.body}</Text> : null}
            </View>
          ))}
        </Card>
        {p.notes ? <Notice tone="neutral" text={p.notes} /> : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function convert(id: string, zoneId: string | null): Promise<ProspectDetail> {
  return api(`/prospects/${id}/convert`, { method: "POST", body: JSON.stringify({ zone_id: zoneId }) });
}

function Detail({ icon, text, dim }: { icon: ReactNode; text: string; dim?: boolean }) {
  return (
    <View style={styles.detail}>
      {icon}
      <Text style={[styles.detailText, dim && { color: colors.textDim }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, minWidth: 0 },
  priority: { ...typography.tiny, color: colors.textMuted, textTransform: "uppercase" },
  name: { ...typography.title, fontSize: 20, color: colors.text, marginTop: spacing.sm + 2 },
  insight: { ...typography.caption, color: colors.textMuted, marginTop: 6, lineHeight: 19 },
  reasons: { marginTop: spacing.sm + 2, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.sm + 4, gap: 2 },
  reason: { ...typography.caption, color: colors.textMuted },
  detail: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 4 },
  detailText: { ...typography.body, color: colors.text, flex: 1 },
  gapTop: { marginTop: spacing.sm },
  gapTopLg: { marginTop: spacing.md },
  lang: { flexDirection: "row", borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: 2 },
  langBtn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6 },
  langBtnOn: { backgroundColor: colors.accent },
  langText: { ...typography.caption, color: colors.textMuted, fontWeight: "600" },
  langTextOn: { color: colors.white },
  message: { marginTop: spacing.sm + 4, minHeight: 140, textAlignVertical: "top", lineHeight: 21 },
  warn: { ...typography.caption, color: colors.warning, marginTop: spacing.sm },
  won: { ...typography.bodyMedium, color: colors.success },
  lostText: { ...typography.caption, color: colors.danger, marginTop: spacing.sm },
  panel: { marginTop: spacing.md, padding: spacing.sm + 4, borderRadius: radius.md, backgroundColor: colors.surface },
  lostPanel: { backgroundColor: colors.dangerDim },
  panelTitle: { ...typography.caption, fontWeight: "600", color: colors.text, marginBottom: spacing.sm },
  noteRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  activity: { borderLeftWidth: 2, borderLeftColor: colors.border, paddingLeft: spacing.sm + 4, paddingVertical: 6, marginTop: 4 },
  activityKind: { fontWeight: "600", color: colors.textMuted },
  activityBody: { ...typography.caption, color: colors.text, marginTop: 2, lineHeight: 19 },
});