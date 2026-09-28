import frappe


@frappe.whitelist()
def get_csrf_token():
    """Return the CSRF token for the current session.

    Only used by the Vite dev server (localhost:3001), where the page is not
    rendered by Frappe and so has no window.csrf_token. In production the token
    is injected by www/planning-app.html.
    """
    return frappe.sessions.get_csrf_token()


@frappe.whitelist()
def get_app_info():
    """What is actually installed on the backend the Vue app is talking to.

    Used by the Settings page. The point of it: erp.pranera.in and your local bench are
    different sites with different code, and "the reservation page errors" is far easier
    to read as "pranera_planning isn't deployed on this backend" than as a stack trace.
    (On a backend that hasn't got this app yet, this very call fails — which is itself
    the answer the page shows.)
    """
    from pranera_planning import __version__
    from pranera_planning.reservation import is_enabled

    hooks = frappe.get_hooks("doc_events").get("Stock Entry", {}).get("validate", [])
    if isinstance(hooks, str):
        hooks = [hooks]

    return {
        "site": frappe.local.site,
        "user": frappe.session.user,
        "app_version": __version__,
        "reservation_doctype": bool(frappe.db.exists("DocType", "Project Stock Reservation")),
        "stock_entry_check_registered": "pranera_planning.reservation.validate_stock_entry" in hooks,
        "enforcement_enabled": bool(is_enabled()),
    }
