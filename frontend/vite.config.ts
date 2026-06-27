/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  // Minimal jsdom test env (WS4). WS1 owns the fuller vitest setup; this
  // block is additive so the WS4 error-boundary render test can run, and is
  // safe to supersede when WS1's config lands.
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
