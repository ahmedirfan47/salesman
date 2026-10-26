import { useState } from "react";
import { Text, ScrollView, KeyboardAvoidingView, Platform, StyleSheet } from "react-native";
import { api } from "../../lib/api";
import { errorText } from "../../lib/format";
import { BackBar, Button, Card, ErrorText, Input, shared } from "../../components/ui";
import { colors, spacing, typography } from "../../theme/theme";

/** Add a shop spotted on the road. It's assigned to whoever adds it. */
export function NewProspectScreen({ onBack, onCreated }: { onBack: () => void; onCreated: (id: string) => void }) {
  const [form, setForm] = useState({ name: "", contact_name: "", phone: "", area: "", address: "", category: "", notes: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    setBusy(true);
    setError("");
    const body: Record<string, string | null> = {};
    for (const [k, v] of Object.entries(form)) body[k] = v.trim() || null;
    try {
      const p = await api("/prospects", { method: "POST", body: JSON.stringify(body) });
      onCreated(p.id);
    } catch (e) {
      setError(errorText(e, "Failed to add the shop"));
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView style={shared.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <BackBar title="Add a shop" onBack={onBack} />
      <ScrollView contentContainerStyle={shared.list} keyboardShouldPersistTaps="handled">
        <ErrorText text={error} />
        <Card>
          <Text style={styles.label}>Shop name *</Text>
          <Input value={form.name} onChangeText={set("name")} placeholder="e.g. Al Noor Grocery" />
          <Text style={styles.label}>Phone (WhatsApp)</Text>
          <Input value={form.phone} onChangeText={set("phone")} placeholder="05…" keyboardType="phone-pad" />
          <Text style={styles.label}>Contact person</Text>
          <Input value={form.contact_name} onChangeText={set("contact_name")} placeholder="Owner or buyer" />
          <Text style={styles.label}>Area / district</Text>
          <Input value={form.area} onChangeText={set("area")} placeholder="e.g. Al Olaya" />
          <Text style={styles.label}>Address</Text>
          <Input value={form.address} onChangeText={set("address")} placeholder="Street, landmark" />
          <Text style={styles.label}>Type of shop</Text>
          <Input value={form.category} onChangeText={set("category")} placeholder="e.g. Supermarket, café" />
          <Text style={styles.label}>Notes</Text>
          <Input
            value={form.notes}
            onChangeText={set("notes")}
            placeholder="What they sell, who to ask for, best time to visit"
            multiline
            style={styles.notes}
          />
        </Card>
        <Button label="Add shop" onPress={save} busy={busy} disabled={!form.name.trim()} style={styles.save} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  label: { ...typography.caption, color: colors.textMuted, fontWeight: "600", marginTop: spacing.sm + 4, marginBottom: 6 },
  notes: { minHeight: 90, textAlignVertical: "top" },
  save: { marginTop: spacing.sm },
});