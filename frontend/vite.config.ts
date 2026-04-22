import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// LAN 内アクセス前提: dev server は 0.0.0.0 でバインドし、
// /api/* は backend(8000) に proxy する。
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VVMC_BACKEND_URL || "http://backend:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
