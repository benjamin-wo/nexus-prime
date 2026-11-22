import * as Haptics from "expo-haptics";
import * as Linking from "expo-linking";
import { useNetworkState } from "expo-network";
import * as WebBrowser from "expo-web-browser";
import { type ComponentType, type Ref, useCallback, useRef, useState } from "react";
import { Share, StyleSheet, Text, useColorScheme, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { WebView, type WebViewMessageEvent } from "react-native-webview";
import type { IOSWebViewProps, ShouldStartLoadRequest } from "react-native-webview/lib/WebViewTypes";

import { type HapticKind, INJECTED_BEFORE_LOAD, originOf, parseMessage } from "../src/bridge";
import { OfflineScreen } from "../src/offline";

// The package types its props as an iOS & Android & Windows intersection that collapses to `never` under
// React 19 typings; this app only runs on iOS, so type it as the iOS props.
const IosWebView = WebView as unknown as ComponentType<IOSWebViewProps & { ref?: Ref<WebView> }>;

// The page's ground (DESIGN.md, Paper), behind the status bar and while the page loads.
const GROUND_LIGHT = "#F3F1EC";
const GROUND_DARK = "#161512";

const SITE_URL = process.env.EXPO_PUBLIC_SITE_URL?.trim();

const HAPTICS: Record<HapticKind, () => Promise<void>> = {
  light: () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light),
  medium: () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium),
  success: () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success),
  warning: () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning),
  error: () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error),
  selection: () => Haptics.selectionAsync(),
};

export default function Home() {
  const insets = useSafeAreaInsets();
  const dark = useColorScheme() === "dark";
  const net = useNetworkState();
  const web = useRef<WebView>(null);
  const [failed, setFailed] = useState(false);
  const site = SITE_URL ? originOf(SITE_URL) : null;

  const retry = useCallback(() => {
    setFailed(false);
    web.current?.reload();
  }, []);

  if (!SITE_URL || !site) {
    return (
      <View style={[styles.center, { backgroundColor: dark ? "#000" : "#fff" }]}>
        <Text style={[styles.title, { color: dark ? "#fff" : "#111" }]}>Nexus is not configured</Text>
        <Text style={{ color: dark ? "#aaa" : "#555", textAlign: "center" }}>
          Set EXPO_PUBLIC_SITE_URL to the address of your Nexus site (see mobile/.env.example), then restart
          Expo.
        </Text>
      </View>
    );
  }

  const onShouldStart = (req: ShouldStartLoadRequest): boolean => {
    const url = req.url;
    if (url === "about:blank") return true;
    // Telegram's own links open the Telegram app, which is how a sign-in code gets approved.
    if (/^(tel|mailto|sms|tg):/i.test(url) || /^https:\/\/(t\.me|telegram\.me)\//i.test(url)) {
      void Linking.openURL(url);
      return false;
    }
    if (req.isTopFrame === false) return true; // embedded frames (maps, widgets) stay in the page
    if (originOf(url) === site) return true;
    if (originOf(url)) void WebBrowser.openBrowserAsync(url);
    return false;
  };

  const onMessage = (event: WebViewMessageEvent) => {
    const msg = parseMessage(event.nativeEvent.data, event.nativeEvent.url, SITE_URL);
    if (!msg) return;
    if (msg.type === "haptic") void HAPTICS[msg.kind]().catch(() => {});
    else if (msg.type === "share") {
      void Share.share({ title: msg.title, message: msg.text ?? "", url: msg.url }).catch(() => {});
    }
  };

  const offline = net.isConnected === false || net.isInternetReachable === false || failed;
  return (
    <View style={[styles.fill, { paddingTop: insets.top, backgroundColor: dark ? GROUND_DARK : GROUND_LIGHT }]}>
      <IosWebView
        ref={web}
        source={{ uri: `${SITE_URL.replace(/\/+$/, "")}/app` }}
        style={[styles.fill, { backgroundColor: dark ? GROUND_DARK : GROUND_LIGHT }]}
        sharedCookiesEnabled
        hideKeyboardAccessoryView
        allowsBackForwardNavigationGestures
        pullToRefreshEnabled
        injectedJavaScriptBeforeContentLoaded={INJECTED_BEFORE_LOAD}
        onShouldStartLoadWithRequest={onShouldStart}
        onMessage={onMessage}
        onError={() => setFailed(true)}
        onHttpError={(e: { nativeEvent: { statusCode: number } }) => e.nativeEvent.statusCode >= 500 && setFailed(true)}
        onLoad={() => setFailed(false)}
      />
      {offline && <OfflineScreen onRetry={retry} />}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  title: { fontSize: 20, fontWeight: "600", marginBottom: 8 },
});
