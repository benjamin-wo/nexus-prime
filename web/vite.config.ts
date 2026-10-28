import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
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
