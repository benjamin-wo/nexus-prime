import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { LockGate } from "../src/lock";

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="auto" />
      <LockGate>
        <Stack screenOptions={{ headerShown: false }} />
      </LockGate>
    </SafeAreaProvider>
  );
}
