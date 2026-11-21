import * as LocalAuthentication from "expo-local-authentication";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { AppState, Pressable, StyleSheet, Text, useColorScheme, View } from "react-native";

/** How long the app may sit in the background before it asks again. */
export const RELOCK_AFTER_MS = 60_000;

/** Face ID (or the passcode) on a cold start and on return after RELOCK_AFTER_MS. The lock is on only
 * when the phone has biometrics enrolled; the page underneath stays mounted so nothing reloads. */
export function LockGate({ children }: { children: ReactNode }) {
  const dark = useColorScheme() === "dark";
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [locked, setLocked] = useState(true);
  const leftAt = useRef<number | null>(null);
  const busy = useRef(false);

  const unlock = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: "Unlock Nexus",
        disableDeviceFallback: false,
      });
      if (result.success) setLocked(false);
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    (async () => {
      const on = (await LocalAuthentication.hasHardwareAsync()) && (await LocalAuthentication.isEnrolledAsync());
      setEnabled(on);
      if (on) void unlock();
      else setLocked(false);
    })();
  }, [unlock]);

  useEffect(() => {
    if (!enabled) return;
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "background") {
        leftAt.current = Date.now();
      } else if (state === "active") {
        const away = leftAt.current === null ? 0 : Date.now() - leftAt.current;
        leftAt.current = null;
        if (away > RELOCK_AFTER_MS) {
          setLocked(true);
          void unlock();
        }
      }
    });
    return () => sub.remove();
  }, [enabled, unlock]);

  return (
    <View style={styles.fill}>
      {children}
      {(enabled === null || locked) && (
        <View style={[styles.cover, { backgroundColor: dark ? "#000" : "#fff" }]}>
          {enabled !== null && (
            <Pressable accessibilityRole="button" onPress={unlock} style={styles.button}>
              <Text style={styles.buttonText}>Unlock Nexus</Text>
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  cover: { ...StyleSheet.absoluteFill, alignItems: "center", justifyContent: "center" },
  button: { backgroundColor: "#2563eb", paddingHorizontal: 28, paddingVertical: 12, borderRadius: 10 },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
});
