# 0003. The iOS app is an Expo shell around the live web app

- **Status:** Proposed
- **Date:** 2026-11-22
- **Build plan:** [`docs/plans/domain-panels.md`](../plans/domain-panels.md) §6.4 and §6.5

## Context

The owner wants an iPhone app. The web app (`web/`, about 23k lines of React) is already phone-first and runs as a Telegram Mini App. The owner has **no Apple Developer account yet**, so development has to work in Expo Go, with no custom native modules and no development build.

Sign-in today is a session cookie plus a CSRF header. The Telegram login widget and the bot's `/web` link are built for a browser: the widget does not work in a WebView, and `/web` opens the system browser, whose cookies a WebView does not share.

## Decision

1. **An Expo app (`mobile/`, Expo Router, TypeScript) that shows the live site in `react-native-webview`.** The page is the product; the shell adds native depth in steps:
   - now (Expo Go): Face ID or passcode lock on a cold start and on return after 60 seconds, haptics, the native share sheet, an offline screen with Retry, external links in the system browser;
   - later, with an Apple account: push notifications, Universal Links, a share extension.
2. **A small versioned bridge.** The shell injects `window.NexusNative = {v: 1, platform: 'ios'}` before the page loads. The page posts `{v: 1, type, ...}` messages (`ready`, `haptic`, `share`); the shell ignores anything malformed, of another version, or sent from another origin. The site's side is `web/src/native.ts`; outside the app it does nothing.
3. **Sign-in from the app uses a device-code flow, as a separate sensitive PR** (not part of this change). `POST /api/auth/device` returns a short code; the user sends `/app CODE` to the bot; the app polls and receives a one-time token; the WebView then loads the existing `/login/link/{token}`. Until then the login page, when inside the app, says sign-in from the app is coming.
4. **Later native screens, route by route, only if earned.** Chat is the first candidate. The shell does not block that, because routes can be swapped from WebView to native one at a time.
5. **Placeholders.** The bundle identifier `com.benjaminwo.nexus` is a placeholder until the Apple account exists. The site address comes from `EXPO_PUBLIC_SITE_URL`; the production address is not in the repo.

## Consequences

- **Good:** one UI to maintain, and web changes reach the app without a store release. The owner can run it on a real iPhone today in Expo Go.
- **App Store Guideline 4.2 (minimum functionality) is the main risk.** A repackaged website can be rejected. The answer is native features that the website cannot offer: biometric lock, haptics, share sheet, offline handling, and, once there is an account, push and Universal Links. Submission waits until push and the device-code sign-in exist.
- **Guideline 5.1.2(i)** requires clear consent before personal data goes to a third-party AI provider. Plan §6.4 adds a consent screen to web onboarding that names the model provider, so the app inherits it.
- The WebView adds an origin check to every bridge message, and links to other origins leave the app, so a compromised third-party page cannot drive native features.
- Expo Go cannot test push or Universal Links; those wait for a development build.
- The CSP in `channels/web/frontend.py` needs no change: the shell loads the site as a top-level page (`frame-ancestors` only restricts framing), and the session cookie is `SameSite=Lax`, which a first-party WebView navigation satisfies.

## Alternatives considered

- **A native rewrite (React Native screens for everything).** About 23k lines of UI to rebuild and keep in step with the web app, two UIs to maintain, and every web change needs an app release. Not justified for one owner.
- **Capacitor.** A similar WebView shell with a faster route to a store, but it needs Xcode and a signed build to run on a device without Expo Go, which means an Apple account first. Expo Go lets development start now, and Expo has a path to native screens per route later.
- **A plain PWA.** Free and already works, but no biometric lock, no reliable push on a store-free path, and no App Store presence.
