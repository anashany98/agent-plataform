import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// El proxy de desarrollo replica el proxy de producción
// (infrastructure/proxy/nginx.conf): `location /api/bridge/` con
// `proxy_pass http://bridge-api:8005/;` — es decir, elimina el prefijo
// `/api/bridge` antes de reenviar al backend.
export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
    target: 'es2020',
  },
  server: {
    proxy: {
      '/api/bridge': {
        target: 'http://localhost:8005',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/bridge/, ''),
      },
    },
  },
});
