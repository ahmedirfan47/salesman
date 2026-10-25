import { useState } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { StatusBar } from "expo-status-bar";
import { AuthProvider, useAuth } from "./src/lib/auth-context";
import { SubscriptionScreen } from "./src/screens/SubscriptionScreen";
import { LoginScreen } from "./src/screens/LoginScreen";
import { HomeScreen } from "./src/screens/HomeScreen";
import { colors } from "./src/theme/theme";

type PreAuthScreen = "subscription" | "login";

/**
 * Root navigator. No routing library -- the app only ever has a handful of
 * top-level states, so a simple switch is clearer than the overhead of a
 * navigation stack: loading -> (subscription | login) -> home.
 */
function RootNavigator() {
  const { me, loading } = useAuth();
  const [preAuthScreen, setPreAuthScreen] = useState<PreAuthScreen>("subscription");

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (!me) {
    if (preAuthScreen === "login") {
      return <LoginScreen onBack={() => setPreAuthScreen("subscription")} />;
    }
    return (
      // Accounts on this app are created by an admin via the web dashboard's
      // Team & Access page, so the pre-auth screen only offers pricing,
      // a contact CTA, and sign-in.
      <SubscriptionScreen onSignIn={() => setPreAuthScreen("login")} />
    );
  }

  return <HomeScreen />;
}

export default function App() {
  return (
    <AuthProvider>
      <StatusBar style="dark" />
      <RootNavigator />
    </AuthProvider>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg },
});