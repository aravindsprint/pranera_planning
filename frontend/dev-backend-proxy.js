// Dev-server only. Forwards /api, /assets, /files and /private to ONE of two backends,
// chosen per request from the `pp_backend` cookie (set by the Settings page):
//
//   live   -> https://erp.pranera.in            (real data; pranera_planning is not deployed there yet)
//   local  -> http://127.0.0.1:8001             (bench --site pranera.com serve --port=8001)
//
// Vite's own `server.proxy` fixes its target when the server starts, which is why this
// is a plugin instead: switching backends is a cookie flip, no restart of `yarn dev`.
// `vite build` never loads this file's hooks (apply: 'serve'); in production the app is
// served by Frappe from the same origin as the API, so there is no proxy at all.
import httpProxy from 'http-proxy'

const COOKIE = 'pp_backend'
const PREFIXES = ['/api', '/assets', '/files', '/private']

function makeProxy(mode, target) {
  const proxy = httpProxy.createProxyServer({
    target,
    changeOrigin: true,
    secure: false,
    // Cookies come back scoped to the ERP host; re-scope to localhost.
    cookieDomainRewrite: 'localhost',
    headers: { Origin: target, Referer: target },
  })

  // node-http-proxy can forward a stray `Expect` header on body-less POSTs (e.g. logout).
  // nginx in front of erp.pranera.in answers that with 417 Expectation Failed and never
  // runs the request. 'start' fires BEFORE the upstream request is built (removing it in
  // 'proxyReq' is too late on current Node — the header is already flushed).
  proxy.on('start', (req) => {
    delete req.headers['expect']
  })

  // Our own switch cookie means nothing to Frappe — don't send it upstream.
  proxy.on('proxyReq', (proxyReq) => {
    const cookie = proxyReq.getHeader('cookie')
    if (!cookie) return
    const cleaned = String(cookie)
      .split(/;\s*/)
      .filter((c) => c && !c.startsWith(`${COOKIE}=`))
      .join('; ')
    if (cleaned) proxyReq.setHeader('cookie', cleaned)
    else proxyReq.removeHeader('cookie')
  })

  // Frappe marks `sid` as Secure because erp.pranera.in is HTTPS, but the dev server is
  // plain http://localhost — browsers silently drop Secure cookies there, so login
  // "succeeds" and the session never sticks. Strip Secure (dev only).
  proxy.on('proxyRes', (proxyRes) => {
    const setCookie = proxyRes.headers['set-cookie']
    if (setCookie) {
      proxyRes.headers['set-cookie'] = setCookie.map((c) =>
        c.replace(/;\s*Secure/gi, '').replace(/;\s*SameSite=None/gi, '; SameSite=Lax')
      )
    }
  })

  // A dead backend should read as a sentence in the UI, not a generic proxy error.
  // The frontend's request() turns `exception: "Type: message"` into the message shown.
  proxy.on('error', (err, req, res) => {
    if (!res || res.headersSent || typeof res.writeHead !== 'function') {
      if (res && typeof res.end === 'function') res.end()
      return
    }
    const hint = mode === 'local'
      ? ' Is `bench --site pranera.com serve --port=8001` running?'
      : ''
    res.writeHead(502, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({
      exception: `BackendUnreachable: Cannot reach the ${mode} backend at ${target} (${err.code || err.message}).${hint}`,
    }))
  })

  return proxy
}

export function backendProxyPlugin({ targets, defaultBackend = 'live' }) {
  const proxies = Object.fromEntries(
    Object.entries(targets).map(([mode, target]) => [mode, makeProxy(mode, target)])
  )
  const cookieRe = new RegExp(`(?:^|;\\s*)${COOKIE}=(\\w+)`)

  const pick = (req) => {
    const m = cookieRe.exec(req.headers.cookie || '')
    return m && proxies[m[1]] ? m[1] : defaultBackend
  }

  return {
    name: 'pranera-dev-backend-proxy',
    apply: 'serve',
    configureServer(server) {
      // Registered directly (not returned as a post-hook) so it runs before Vite's own
      // middlewares — these paths must never fall through to the SPA fallback.
      server.middlewares.use((req, res, next) => {
        const url = req.url || ''
        const hit = PREFIXES.some((p) => url === p || url.startsWith(`${p}/`) || url.startsWith(`${p}?`))
        if (!hit) return next()
        proxies[pick(req)].web(req, res)
      })
    },
  }
}
