// Dev-only backend switch. The Vite dev server (dev-backend-proxy.js) forwards /api etc.
// to either the live site or your local bench, chosen per request by the `pp_backend`
// cookie this module sets. In a production build __PP_BACKENDS__ is null, so isDev is
// false and none of this does anything — the app just talks to its own origin.
/* global __PP_BACKENDS__ */
const cfg = typeof __PP_BACKENDS__ !== 'undefined' ? __PP_BACKENDS__ : null

export const isDev = import.meta.env.DEV && !!cfg
export const BACKENDS = {
  live:  { key: 'live',  label: 'erp.pranera.in', short: 'LIVE',  target: cfg?.targets?.live  || '' },
  local: { key: 'local', label: 'Local bench',    short: 'LOCAL', target: cfg?.targets?.local || '' },
}
const COOKIE = 'pp_backend'

export function currentBackend() {
  if (!isDev) return null
  const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${COOKIE}=(\\w+)`))
  return (m && BACKENDS[m[1]] ? m[1] : cfg.default) || 'live'
}

// Point the dev server at a different backend. Sessions on the two sites are separate
// (both use a cookie called `sid` on localhost), so the caller must sign out of the old
// one first and land on the login page afterwards — see BackendSwitch.vue.
export function setBackend(mode) {
  document.cookie = `${COOKIE}=${mode}; path=/; max-age=31536000; SameSite=Lax`
  // `user_id` is what tells the app "already signed in". Left over from the other site it
  // would make the app think you are, while every request comes back as Guest.
  document.cookie = 'user_id=; path=/; max-age=0'
}

export function backendLabel() {
  if (!isDev) return window.location.origin
  const b = BACKENDS[currentBackend()]
  return `${b.label} — ${b.target} (dev proxy)`
}
