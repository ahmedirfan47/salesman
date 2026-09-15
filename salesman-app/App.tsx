import { StatusBar } from "expo-status-bar";
import { SubscriptionScreen } from "./src/screens/SubscriptionScreen";

export default function App() {
  return (
    <>
      <StatusBar style="dark" />
      <SubscriptionScreen
        onContinue={(planId, period) => {
          // TODO(billing): route to the real checkout flow once payments exist.
          console.log("Selected plan:", planId, "billed", period);
        }}
        onSignIn={() => {
          // TODO(auth): navigate to the sign-in screen.
          console.log("Sign in tapped");
        }}
      />
    </>
  );
}