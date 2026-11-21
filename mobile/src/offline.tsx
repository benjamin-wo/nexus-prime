import { Pressable, StyleSheet, Text, useColorScheme, View } from "react-native";

export function OfflineScreen({ onRetry, detail }: { onRetry: () => void; detail?: string }) {
  const dark = useColorScheme() === "dark";
  return (
    <View style={[styles.box, { backgroundColor: dark ? "#000" : "#fff" }]}>
      <Text style={[styles.title, { color: dark ? "#fff" : "#111" }]}>You're offline</Text>
      <Text style={[styles.body, { color: dark ? "#aaa" : "#555" }]}>
        {detail ?? "Nexus needs a connection to show your data. Check your network and try again."}
      </Text>
      <Pressable accessibilityRole="button" onPress={onRetry} style={styles.button}>
        <Text style={styles.buttonText}>Retry</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { ...StyleSheet.absoluteFill, alignItems: "center", justifyContent: "center", padding: 32 },
  title: { fontSize: 22, fontWeight: "600", marginBottom: 8 },
  body: { fontSize: 15, textAlign: "center", marginBottom: 24 },
  button: { backgroundColor: "#2563eb", paddingHorizontal: 28, paddingVertical: 12, borderRadius: 10 },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
});
