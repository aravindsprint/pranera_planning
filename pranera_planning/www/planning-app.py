import os

import frappe

# Never cache: the rendered HTML embeds a per-session CSRF token.
no_cache = 1


def get_context(context):
    context.no_cache = 1

    if frappe.session.user != "Guest":
        context.csrf_token = frappe.sessions.get_csrf_token()

    # index.js / index.css keep the same filename on every Vite build (only the
    # lazy page chunks are content-hashed), and Frappe serves /assets with a
    # long max-age. Tagging the URL with the bundle's mtime forces browsers to
    # refetch exactly when a new build is deployed. Same fix as pranera_knit.
    bundle = frappe.get_app_path("pranera_planning", "public", "planning_app", "index.js")
    try:
        context.asset_version = int(os.path.getmtime(bundle))
    except OSError:
        context.asset_version = ""
