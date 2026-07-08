import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo (npm run dev) el proxy de Vite replica las mismas rutas /api/*
// que nginx sirve en producción — el código de la app no cambia entre entornos.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/api/auth": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/auth/, "/auth"),
      },
      "/api/logs": {
        target: "http://localhost:8010",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/logs/, "/logs"),
      },
      "/api/analysis": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/analysis/, ""),
      },
      "/api/alerts": {
        target: "http://localhost:8003",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/alerts/, "/alerts"),
      },
      "/api/items": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
