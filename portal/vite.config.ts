import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// El proxy de desarrollo replica el proxy de producción
// El proxy replica las reglas de producción: elimina `/api/bridge` en las
// rutas canónicas y conserva el prefijo en `/api/bridge/import*`, porque esos
// endpoints del backend están registrados con el prefijo completo.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    build: {
      sourcemap: false,
      target: "es2020",
    },
    server: {
      proxy: {
        "/api/bridge": {
          target: env.VITE_DEV_API_TARGET || "http://localhost:8005",
          changeOrigin: true,
          rewrite: (path) =>
            path.startsWith("/api/bridge/import")
              ? path
              : path.replace(/^\/api\/bridge/, ""),
        },
      },
    },
  };
});
