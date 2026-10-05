// Thin client for Frappe's REST + whitelisted-method endpoints.
// Same-origin in production; in dev the Vite proxy forwards to erp.pranera.in.
import { CSRF_ENDPOINTS } from '@/config/app'

// ── CSRF / session ───────────────────────────────────────────────────────────
let _csrf = ''

function cookie(name) {
  return document.cookie.split('; ').find((r) => r.startsWith(name + '='))?.split('=')[1] || ''
}

export async function ensureCSRF() {
  if (_csrf) return _csrf
  // 1. Injected by www/planning-app.html (production)
  if (window.csrf_token) {
    _csrf = window.csrf_token
    return _csrf
  }
  // 2. Cookie fallback
  const fromCookie = cookie('csrftoken') || cookie('X-Frappe-CSRF-Token')
  if (fromCookie) { _csrf = fromCookie; return _csrf }
  // 3. Ask the server (dev proxy)
  for (const method of CSRF_ENDPOINTS) {
    try {
      const r = await fetch(`/api/method/${method}`, { credentials: 'include' })
      if (!r.ok) continue
      const d = await r.json()
      if (d?.message) { _csrf = d.message; window.csrf_token = d.message; return _csrf }
    } catch { /* try the next endpoint */ }
  }
  console.warn('ensureCSRF: no token — not logged in, or none of CSRF_ENDPOINTS exist on the backend')
  return _csrf
}

// Login and logout both issue a new session (and a new token). Forget the old
// one, otherwise the next request fails with a silent CSRFTokenError 403.
export function resetCSRF() {
  _csrf = ''
  window.csrf_token = ''
}

// Reads the logged-in user from the `user_id` cookie (set by Frappe on login).
export function readSessionFromCookie() {
  window.__FRAPPE_SESSION__ = {
    user: decodeURIComponent(cookie('user_id') || '') || 'Guest',
  }
  return window.__FRAPPE_SESSION__
}

export function isLoggedIn() {
  const user = window.__FRAPPE_SESSION__?.user
  return !!user && user !== 'Guest'
}

export async function initCSRF() {
  readSessionFromCookie()
  if (isLoggedIn()) await ensureCSRF()
}

// ── Errors ───────────────────────────────────────────────────────────────────
export class ApiError extends Error {
  constructor(message, status, data) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

// Frappe error payload -> one readable line (instead of a Python traceback).
function extractServerError(data, fallback = 'Request failed') {
  try {
    const msgs = JSON.parse(data?._server_messages || '[]')
    if (msgs.length) {
      const last = JSON.parse(msgs[msgs.length - 1])
      const text = String(last.message || last).replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '').trim()
      if (text) return text
    }
  } catch { /* fall through */ }
  if (data?.exception) {
    const parts = String(data.exception).split(':')
    return (parts.length > 1 ? parts.slice(1).join(':') : parts[0]).trim()
  }
  if (data?.exc) {
    try {
      const lines = String(JSON.parse(data.exc)[0] || '').trim().split('\n')
      return lines[lines.length - 1].trim()
    } catch { /* fall through */ }
  }
  return fallback
}

async function request(url, { method = 'GET', headers = {}, body } = {}) {
  const h = { Accept: 'application/json', ...headers }
  if (method !== 'GET') h['X-Frappe-CSRF-Token'] = await ensureCSRF()

  const res = await fetch(url, { method, headers: h, body, credentials: 'include' })

  let data = null
  try { data = await res.json() } catch { /* non-JSON body */ }

  if (!res.ok || data?.exc) {
    throw new ApiError(extractServerError(data, res.statusText || 'Request failed'), res.status, data)
  }
  if (data === null) {
    // Typically the dev proxy hit a path it doesn't forward and got Vite's HTML.
    throw new ApiError('Server returned a non-JSON response — check the dev proxy target', res.status)
  }
  return data
}

const json = (obj) => JSON.stringify(obj)

// ── Whitelisted methods / Server Scripts ─────────────────────────────────────
// Returns the full response ({ message, ... }). Object args are JSON-encoded.
export function call(method, args = {}) {
  const body = new URLSearchParams()
  for (const [k, v] of Object.entries(args)) {
    if (v === undefined || v === null) continue          // a null would arrive as the text "null"
    body.append(k, typeof v === 'object' && v !== null ? json(v) : v)
  }
  return request(`/api/method/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })
}
export const callMessage = (method, args) => call(method, args).then((r) => r.message)
export const getCurrentUser = () => callMessage('frappe.auth.get_logged_user')

// ── Resource API ─────────────────────────────────────────────────────────────
function listParams({ filters = [], orFilters = [], fields = ['name'], orderBy, groupBy, limit, start }) {
  const p = new URLSearchParams({ filters: json(filters), fields: json(fields) })
  if (orFilters?.length) p.set('or_filters', json(orFilters))
  if (orderBy) p.set('order_by', orderBy)
  if (groupBy) p.set('group_by', groupBy)
  if (limit !== undefined) p.set('limit_page_length', limit)   // 0 = no limit
  if (start !== undefined) p.set('limit_start', start)
  return p
}

const resource = (doctype, name) =>
  `/api/resource/${encodeURIComponent(doctype)}` + (name !== undefined ? `/${encodeURIComponent(name)}` : '')

// Filters are Frappe-style: [['Work Order', 'status', '=', 'Draft']] or
// [['status', '=', 'Draft']]. Fields may use aliases: 'total_qty as qty'.
export async function getList(doctype, { filters, orFilters, fields, limit = 200, orderBy, groupBy } = {}) {
  const data = await request(`${resource(doctype)}?${listParams({ filters, orFilters, fields, limit, orderBy, groupBy })}`)
  return data.data || []
}

// Every matching row, paged. A single request silently truncates at
// limit_page_length, and with no order_by Frappe sorts by `modified desc`
// across the whole doctype, so a plain limit can drop rows unpredictably.
export async function getAllList(doctype, { filters, orFilters, fields, pageSize = 500, orderBy = 'name asc', maxPages = 40 } = {}) {
  const all = []
  for (let page = 0; page < maxPages; page++) {
    const data = await request(
      `${resource(doctype)}?${listParams({ filters, orFilters, fields, orderBy, limit: pageSize, start: page * pageSize })}`
    )
    const rows = data.data || []
    all.push(...rows)
    if (rows.length < pageSize) break
  }
  return all
}

export async function getDoc(doctype, name) {
  return (await request(resource(doctype, name))).data
}

export async function createDoc(doctype, doc) {
  const data = await request(resource(doctype), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: json(doc),
  })
  return data.data
}

export async function updateDoc(doctype, name, doc) {
  const data = await request(resource(doctype, name), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: json(doc),
  })
  return data.data
}

export const deleteDoc = (doctype, name) => request(resource(doctype, name), { method: 'DELETE' })

export const getCount = (doctype, filters = []) =>
  callMessage('frappe.client.get_count', { doctype, filters })
