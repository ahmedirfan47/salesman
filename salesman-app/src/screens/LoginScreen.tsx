import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from "react-native";
import { colors, radius, spacing, typography } from "../theme/theme";
import { useAuth } from "../lib/auth-context";

interface Props {
  onBack?: () => void;
}

export function LoginScreen({ onBack }: Props) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    setError("");
    setLoading(true);
    try {
      await login(email.trim(), password);
      // On success, AuthProvider's `me` updates and the app's root
      // navigator (App.tsx) switches away from this screen automatically.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <View style={styles.content}>
          {onBack && (
            <Pressable onPress={onBack} style={styles.backLink}>
              <Text style={styles.backText}>← Back</Text>
            </Pressable>
          )}

          <Text style={styles.brand}>
            Salesman<Text style={{ color: colors.accent }}>.</Text>
          </Text>
          <Text style={styles.headline}>Sign in</Text>
          <Text style={styles.sub}>Use the account your admin set up for you.</Text>

          <View style={styles.field}>
            <Text style={styles.label}>Email</Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="you@company.com"
              placeholderTextColor={colors.textDim}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
            />
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              placeholderTextColor={colors.textDim}
              secureTextEntry
            />
          </View>

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <Pressable
            style={[styles.button, loading && styles.buttonDisabled]}
            onPress={handleSubmit}
            disabled={loading || !email || !password}
          >
            {loading ? (
              <ActivityIndicator color={colors.white} />
            ) : (
              <Text style={styles.buttonText}>Sign in</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  content: { flex: 1, justifyContent: "center", paddingHorizontal: spacing.lg },
  backLink: { position: "absolute", top: spacing.lg, left: spacing.lg },
  backText: { ...typography.body, color: colors.textMuted },
  brand: { ...typography.heading, color: colors.text, letterSpacing: 1, marginBottom: spacing.xs },
  headline: { ...typography.display, color: colors.text },
  sub: { ...typography.body, color: colors.textMuted, marginTop: spacing.xs, marginBottom: spacing.xl },
  field: { marginBottom: spacing.md },
  label: { ...typography.caption, color: colors.textMuted, marginBottom: spacing.xs },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontSize: 15,
    color: colors.text,
    backgroundColor: colors.white,
  },
  error: { ...typography.caption, color: "#DC2626", marginBottom: spacing.md },
  button: {
    marginTop: spacing.sm,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingVertical: 16,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.7 },
  buttonText: { ...typography.heading, color: colors.white },
});