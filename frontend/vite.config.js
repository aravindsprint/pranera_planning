import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { backendProxyPlugin } from './dev-backend-proxy.js'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, __dirname, '')
  // Dev-server only. The dev server can forward to the live site or to your local bench;
  // which one is decided per request by the Settings page (see dev-backend-proxy.js), so
  // switching never needs a restart. Production is served by Frappe from the same origin
  // as the API — no proxy exists there.
  const LIVE = env.VITE_LIVE_TARGET || 'https://erp.pranera.in'
  const LOCAL = env.VITE_LOCAL_TARGET || 'http://127.0.0.1:8001'
  // Used until the Settings page has picked one (i.e. no cookie yet).
  const DEFAULT_BACKEND = env.VITE_DEFAULT_BACKEND === 'local' ? 'local' : 'live'
  const serving = command === 'serve'

  return {
    // Dev: served from '/'.  Build: served by Frappe from the app's public/ folder.
    base: command === 'serve' ? '/' : '/assets/pranera_planning/planning_app/',

    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },

    server: {
      // 3001 so it can run beside pranera_knit (3000). Cookies are shared across
      // localhost ports, so logging in on one also logs you in on the other.
      port: 3001,
    },

    build: {
      outDir: path.resolve(__dirname, '../pranera_planning/public/planning_app'),
      emptyOutDir: true,
      // One CSS file, so www/planning-app.html can reference a fixed name.
      cssCodeSplit: false,
      rollupOptions: {
        input: path.resolve(__dirname, 'index.html'),
        output: {
          entryFileNames: 'index.js',
          chunkFileNames: 'chunks/[name]-[hash].js',
          assetFileNames: (info) => {
            const name = info.name || ''
            return name.endsWith('.css') ? 'index.css' : 'assets/[name]-[hash][extname]'
          },
        },
      },
    },

    // Read by src/config/backend.js. null in a production build, so nothing about the
    // dev backends (or that a switch exists) ships to erp.pranera.in.
    define: {
      __PP_BACKENDS__: serving
        ? JSON.stringify({ default: DEFAULT_BACKEND, targets: { live: LIVE, local: LOCAL } })
        : 'null',
    },

    plugins: [
      vue(),
      ...(serving ? [backendProxyPlugin({ targets: { live: LIVE, local: LOCAL }, defaultBackend: DEFAULT_BACKEND })] : []),
    ],
  }
})
