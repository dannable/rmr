import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, requests to /api and /auth are proxied to the FastAPI server.
// Cookies set by FastAPI flow through the proxy, so the SPA shares the
// 5173 origin with no CORS headaches during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/auth": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
});
