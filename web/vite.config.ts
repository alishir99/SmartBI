import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The API lives on a different origin in dev; proxy /api so the browser sees one origin
// and SSE is not subject to CORS preflight on the Authorization header.
// `loadEnv` reads .env files rather than process.env, which keeps this config free of
// Node globals — and therefore free of an @types/node dependency.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: env.VITE_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
    test: {
      // Only the component tests need a DOM; the pure-function suites do not care, and
      // per-file `@vitest-environment` comments would be one more thing to remember.
      environment: 'jsdom',
      restoreMocks: true,
    },
  }
})
