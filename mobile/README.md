# Nexus iOS app (Expo shell)

A thin native shell: a full-screen WebView of the live Nexus site, plus native features (Face ID lock,
haptics, share sheet, offline screen). See [ADR 0003](../docs/adr/0003-ios-app-shell.md).

## Run it in Expo Go (no Apple Developer account needed)

1. Install **Expo Go** from the App Store on the iPhone.
2. `cd mobile && cp .env.example .env` and set `EXPO_PUBLIC_SITE_URL` to your site (`https://...`).
3. `npm install && npx expo start`
4. Scan the QR code with the iPhone camera. The Mac and phone must be on the same Wi-Fi, or add `--tunnel`.

## Test locally: web, iOS Simulator, Android Emulator

`scripts/dev-local.sh` starts everything on this Mac's Wi-Fi address, so a phone, the simulator and the
emulator all use the same origin (the backend accepts one, `WEB_ORIGIN`, which the script sets):

```bash
scripts/dev-local.sh web       # backend + web app; open the printed address on a phone on the same Wi-Fi
scripts/dev-local.sh ios       # the same, plus this shell in the iOS Simulator (Xcode needed, no Apple account)
scripts/dev-local.sh android   # the same, plus this shell in the Android Emulator (Android Studio needed)
```

- It needs Docker, uv, Node 22 and your filled-in `.env` at the repo root. It uses its own database
  container (`nexus-local-db` on port 5434, kept between runs), never the `.env`'s `DATABASE_URL`, and turns
  background jobs off so nothing is sent on Telegram.
- Sign in with **Try the demo** on the login page: a private demo account with made-up data
  (`DEMO_ENABLED` is on). Health starts off; turn it on from the Health tab.
- Expo Go asks you to sign in to Expo once (`npx expo login`); since May 2026 it only opens projects you own.
- In the iOS Simulator: Features > Face ID fakes a match or a failure; drag images onto it to add them to
  Photos (there is no camera). Haptics don't vibrate.
- In the Android Emulator: Extended controls > Fingerprint fakes a touch. Health Connect is built into
  Android 14 and later.
- Native features beyond Expo Go (Apple Health, Health Connect, push) need a development build:
  `npx expo run:ios` / `npx expo run:android`, still free in the simulator and emulator.

## Layout

- `app/index.tsx`: the WebView, external links, haptic and share handling.
- `src/bridge.ts`: the versioned message protocol with `web/src/native.ts`. Messages from another origin are ignored.
- `src/lock.tsx`: Face ID or passcode on start and after 60 seconds in the background (only if biometrics are enrolled).
- `src/offline.tsx`: the offline screen with Retry.

## Not available in Expo Go

- Push notifications and Universal Links (need an Apple Developer account and a development build).
- Sign-in from the app uses the device-code flow (#294): the app shows a code, you send `/app CODE` to the
  bot, and the app signs in.
- The bundle identifier `com.benjaminwo.nexus` is a placeholder.

## Checks

`npx tsc --noEmit` and `npx expo-doctor`.
