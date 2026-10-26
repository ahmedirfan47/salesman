import type { ReactNode } from "react";
import {
  View,
  Text,
  Pressable,
  TextInput,
  ActivityIndicator,
  StyleSheet,
  type TextInputProps,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { ChevronLeft, type LucideIcon } from "lucide-react-native";
import { colors, radius, spacing, typography } from "../theme/theme";

/** Small shared building blocks so every screen looks and behaves the same. */

type ButtonVariant = "primary" | "outline" | "ghost" | "danger" | "whatsapp";

export function Button({
  label,
  onPress,
  variant = "primary",
  icon: Icon,
  disabled,
  busy,
  small,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  icon?: LucideIcon;
  disabled?: boolean;
  busy?: boolean;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const v = VARIANTS[variant];
  const off = disabled || busy;
  return (
    <Pressable
      onPress={onPress}
      disabled={off}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: v.bg, borderColor: v.border },
        pressed && !off && { opacity: 0.85 },
        off && styles.buttonOff,
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator size="small" color={v.fg} />
      ) : (
        Icon && <Icon size={small ? 15 : 17} color={v.fg} />
      )}
      <Text style={[small ? styles.buttonTextSmall : styles.buttonText, { color: v.fg }]}>{label}</Text>
    </Pressable>
  );
}

const VARIANTS: Record<ButtonVariant, { bg: string; fg: string; border: string }> = {
  primary: { bg: colors.accent, fg: colors.white, border: colors.accent },
  outline: { bg: colors.white, fg: colors.text, border: colors.borderStrong },
  ghost: { bg: "transparent", fg: colors.textMuted, border: "transparent" },
  danger: { bg: colors.danger, fg: colors.white, border: colors.danger },
  whatsapp: { bg: colors.whatsapp, fg: colors.white, border: colors.whatsapp },
};

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "violet";

const TONES: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: colors.surfaceStrong, fg: colors.textMuted },
  accent: { bg: colors.accentDim, fg: colors.accent },
  success: { bg: colors.successDim, fg: colors.success },
  warning: { bg: colors.warningDim, fg: colors.warning },
  danger: { bg: colors.dangerDim, fg: colors.danger },
  violet: { bg: colors.violetDim, fg: colors.violet },
};

export function Badge({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  const t = TONES[tone];
  return (
    <View style={[styles.badge, { backgroundColor: t.bg }]}>
      <Text style={[styles.badgeText, { color: t.fg }]}>{label}</Text>
    </View>
  );
}

export function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      style={[styles.chip, active && styles.chipActive]}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function SectionTitle({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={style}>
      <Text style={styles.sectionTitle}>{children}</Text>
    </View>
  );
}

export function Loading() {
  return (
    <View style={styles.centered}>
      <ActivityIndicator color={colors.accent} />
    </View>
  );
}

export function ErrorText({ text }: { text: string }) {
  if (!text) return null;
  return <Text style={styles.error}>{text}</Text>;
}

export function Notice({ text, tone = "success" }: { text: string; tone?: Tone }) {
  if (!text) return null;
  const t = TONES[tone];
  return (
    <View style={[styles.notice, { backgroundColor: t.bg }]}>
      <Text style={[styles.noticeText, { color: t.fg }]}>{text}</Text>
    </View>
  );
}

export function Empty({ text }: { text: string }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyText}>{text}</Text>
    </View>
  );
}

export function Input({ style, ...props }: TextInputProps) {
  return <TextInput placeholderTextColor={colors.textDim} style={[styles.input, style]} {...props} />;
}

/** Title row for a pushed screen (detail, new order...) with a back button. */
export function BackBar({ title, onBack, right }: { title: string; onBack: () => void; right?: ReactNode }) {
  return (
    <View style={styles.backBar}>
      <Pressable onPress={onBack} hitSlop={10} style={styles.backButton} accessibilityRole="button" accessibilityLabel="Back">
        <ChevronLeft size={22} color={colors.accent} />
        <Text style={styles.backText}>Back</Text>
      </Pressable>
      <Text style={styles.backTitle} numberOfLines={1}>{title}</Text>
      <View style={styles.backRight}>{right}</View>
    </View>
  );
}

/** Label / value row used in detail screens. */
export function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      {typeof value === "string" ? <Text style={styles.rowValue}>{value}</Text> : value}
    </View>
  );
}

export const shared = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  list: { padding: spacing.md, paddingBottom: spacing.xxl, backgroundColor: colors.bg, flexGrow: 1 },
  chips: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  title: { ...typography.bodyMedium, color: colors.text },
  meta: { ...typography.caption, color: colors.textMuted, marginTop: 2 },
  dim: { ...typography.caption, color: colors.textDim },
  between: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  inline: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
});

const styles = StyleSheet.create({
  button: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingVertical: 11,
    paddingHorizontal: 16,
    minHeight: 44,
  },
  buttonSmall: { paddingVertical: 7, paddingHorizontal: 12, minHeight: 36 },
  buttonOff: { opacity: 0.5 },
  buttonText: { ...typography.bodyMedium, fontWeight: "600" },
  buttonTextSmall: { ...typography.caption, fontWeight: "600" },
  badge: { borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2, alignSelf: "flex-start" },
  badgeText: { fontSize: 11, fontWeight: "600" },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.white,
    borderRadius: radius.pill,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { ...typography.caption, color: colors.textMuted, fontWeight: "500" },
  chipTextActive: { color: colors.white },
  card: {
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  sectionTitle: { ...typography.tiny, color: colors.textMuted, marginBottom: spacing.sm, marginTop: spacing.md },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg, padding: spacing.lg },
  error: { ...typography.caption, color: colors.danger, marginBottom: spacing.sm },
  notice: { borderRadius: radius.md, padding: spacing.sm + 4, marginBottom: spacing.sm },
  noticeText: { ...typography.caption, fontWeight: "500" },
  empty: { padding: spacing.xl, alignItems: "center", backgroundColor: colors.surface, borderRadius: radius.lg },
  emptyText: { ...typography.body, color: colors.textDim, textAlign: "center" },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 11,
    fontSize: 15,
    color: colors.text,
    backgroundColor: colors.white,
  },
  backBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.white,
  },
  backButton: { flexDirection: "row", alignItems: "center", paddingRight: spacing.xs },
  backText: { ...typography.bodyMedium, color: colors.accent },
  backTitle: { ...typography.bodyMedium, color: colors.text, flex: 1, fontWeight: "600" },
  backRight: { minWidth: 40, alignItems: "flex-end" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowLabel: { ...typography.caption, color: colors.textMuted },
  rowValue: { ...typography.caption, color: colors.text, fontWeight: "500", flexShrink: 1, textAlign: "right" },
});