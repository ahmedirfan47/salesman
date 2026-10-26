import { useEffect } from "react";
import { BackHandler } from "react-native";

/**
 * Android hardware back: while `active`, back runs `onBack` instead of
 * closing the app. Used by screens pushed inside a tab (details, forms).
 */
export function useBack(active: boolean, onBack: () => void) {
  useEffect(() => {
    if (!active) return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      onBack();
      return true;
    });
    return () => sub.remove();
  }, [active, onBack]);
}