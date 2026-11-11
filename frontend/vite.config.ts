/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // Set VITE_API_TARGET in frontend/.env.local to point the dev server at another backend.
  const env = loadEnv(mode, ".", "VITE_");
  const apiTarget = env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true, ws: true },
        "/health": { target: apiTarget, changeOrigin: true },
        "/ready": { target: apiTarget, changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
      css: false,
    },
  };
});
