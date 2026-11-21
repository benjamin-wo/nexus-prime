# Nexus iOS app (Expo shell)

A thin native shell: a full-screen WebView of the live Nexus site, plus native features (Face ID lock,
haptics, share sheet, offline screen). See [ADR 0003](../docs/adr/0003-ios-app-shell.md).

## Run it in Expo Go (no Apple Developer account needed)

1. Install **Expo Go** from the App Store on the iPhone.
2. `cd mobile && cp .env.example .env` and set `EXPO_PUBLIC_SITE_URL` to your site (`https://...`).
3. `npm install && npx expo start`
4. Scan the QR code with the iPhone camera. The Mac and phone must be on the same Wi-Fi, or add `--tunnel`.

## Point it at a local dev server

Run the web app so the phone can reach it: `cd web && npm run dev -- --host` (note the Network address,
for example `http://192.168.1.20:5173`), then set `EXPO_PUBLIC_SITE_URL` to that address and restart Expo.
The API must be reachable from the same origin (the Vite proxy handles `/api`).

## Layout

- `app/index.tsx`: the WebView, external links, haptic and share handling.
- `src/bridge.ts`: the versioned message protocol with `web/src/native.ts`. Messages from another origin are ignored.
- `src/lock.tsx`: Face ID or passcode on start and after 60 seconds in the background (only if biometrics are enrolled).
- `src/offline.tsx`: the offline screen with Retry.

## Not available in Expo Go

- Push notifications and Universal Links (need an Apple Developer account and a development build).
- Sign-in from the app: the Telegram widget does not work in a WebView and the device-code flow is not built
  yet (ADR 0003). For now the login page tells the user so.
- The bundle identifier `com.benjaminwo.nexus` is a placeholder.

## Checks

`npx tsc --noEmit` and `npx expo-doctor`.
