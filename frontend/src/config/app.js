// App-wide constants. Change things here, not inside components.

export const APP_TITLE = 'Planning'

// URL prefix the app lives under. Must match hooks.py -> website_route_rules
// and the www/planning-app.* filenames.
export const APP_BASE = '/planning-app'

// Frappe roles allowed to open the app. Empty = any logged-in ERPNext user.
// This only hides the UI; real access control is always the DocType permissions.
export const ALLOWED_ROLES = []

// Endpoints that return the session's CSRF token, tried in order. Only needed on
// the Vite dev server: in production Frappe injects window.csrf_token itself.
//  - knit_get_csrf: Server Script already live on erp.pranera.in (used by pranera_knit)
//  - pranera_planning...: same thing, shipped with this app once it is deployed
export const CSRF_ENDPOINTS = [
  'knit_get_csrf',
  'pranera_planning.api.common.get_csrf_token',
]
