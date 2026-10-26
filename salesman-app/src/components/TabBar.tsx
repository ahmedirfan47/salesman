import { View, Text, Pressable, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { LucideIcon } from "lucide-react-native";
import { colors, typography } from "../theme/theme";

export type TabItem<K extends string> = { key: K; label: string; icon: LucideIcon; badge?: number };

/** Bottom tab bar. Only shown when a user has more than one tab. */
export function TabBar<K extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: TabItem<K>[];
  active: K;
  onChange: (key: K) => void;
}) {
  return (
    <SafeAreaView edges={["bottom"]} style={styles.safe}>
      <View style={styles.bar}>
        {tabs.map(({ key, label, icon: Icon, badge }) => {
          const on = key === active;
          const tint = on ? colors.accent : colors.textDim;
          return (
            <Pressable
              key={key}
              onPress={() => onChange(key)}
              style={styles.tab}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              accessibilityLabel={label}
            >
              <View>
                <Icon size={22} color={tint} strokeWidth={on ? 2.3 : 1.8} />
                {badge ? (
                  <View style={styles.badge}>
                    <Text style={styles.badgeText}>{badge > 99 ? "99+" : badge}</Text>
                  </View>
                ) : null}
              </View>
              <Text style={[styles.label, { color: tint }]} numberOfLines={1}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: colors.border },
  bar: { flexDirection: "row" },
  tab: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: 8, paddingBottom: 6, gap: 3 },
  label: { ...typography.caption, fontSize: 11, fontWeight: "600" },
  badge: {
    position: "absolute",
    top: -4,
    right: -10,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 4,
    backgroundColor: colors.danger,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { color: colors.white, fontSize: 10, fontWeight: "700" },
});