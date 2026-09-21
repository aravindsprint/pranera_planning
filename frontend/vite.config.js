import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, __dirname, '')
  // Dev-server only — `vite build` never reads `server.proxy`. In production the
  // app is served by Frappe from the same origin as the API, so no proxy exists.
  const target = env.VITE_PROXY_TARGET || 'https://erp.pranera.in'

  const passthrough = { target, changeOrigin: true, secure: false }

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
      proxy: command === 'serve' ? {
        '/api': {
          ...passthrough,
          ws: true,
          // Cookies come back scoped to the ERP host; re-scope to localhost.
          cookieDomainRewrite: 'localhost',
          headers: { Origin: target, Referer: target },
          configure(proxy) {
            // node-http-proxy can forward a stray `Expect` header on body-less
            // POSTs (e.g. logout). nginx in front of erp.pranera.in answers that
            // with 417 Expectation Failed and never runs the request.
            // Strip it on 'start', i.e. BEFORE the upstream request is built.
            // (pranera_knit does this in 'proxyReq' via removeHeader, which is
            // too late on current Node: the header is already flushed by then.)
            proxy.on('start', (req) => {
              delete req.headers['expect']
            })
            // Frappe marks `sid` as Secure because erp.pranera.in is HTTPS, but
            // the dev server is plain http://localhost — browsers silently drop
            // Secure cookies there, so login "succeeds" and the session never
            // sticks. Strip Secure (dev only) so the cookie is actually stored.
            proxy.on('proxyRes', (proxyRes) => {
              const setCookie = proxyRes.headers['set-cookie']
              if (setCookie) {
                proxyRes.headers['set-cookie'] = setCookie.map((c) =>
                  c.replace(/;\s*Secure/gi, '').replace(/;\s*SameSite=None/gi, '; SameSite=Lax')
                )
              }
            })
          },
        },
        '/assets': passthrough,
        '/files': passthrough,
        '/private': passthrough,
      } : undefined,
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

    plugins: [vue()],
  }
})
