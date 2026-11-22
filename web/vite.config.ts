import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    // Fonts must stay files: the CSP (font-src 'self') blocks data: URIs.
    assetsInlineLimit: (file) => (/\.woff2?$/.test(file) ? false : undefined),
    rollupOptions: {
      // Two entries: the app, and the public pages (landing, privacy, terms, support), which are
      // plain prerendered HTML that the server serves at / (for visitors), /privacy, /terms and /support.
      input: {
        index: resolve(__dirname, "index.html"),
        landing: resolve(__dirname, "landing/index.html"),
        privacy: resolve(__dirname, "landing/privacy.html"),
        terms: resolve(__dirname, "landing/terms.html"),
        support: resolve(__dirname, "landing/support.html"),
      },
      output: {
        // The libraries every page shares change far less often than the app, so keep them in
        // their own file: a deploy then leaves the browser's cached copy of it alone.
        manualChunks: (id) =>
          /node_modules\/(react|react-dom|react-router|react-router-dom|scheduler|@tanstack)\//.test(id) ? "vendor" : undefined,
      },
    },
  },
  server: { proxy: { "/api": "http://localhost:8000", "/healthz": "http://localhost:8000" } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
