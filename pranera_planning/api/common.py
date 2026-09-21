import frappe


@frappe.whitelist()
def get_csrf_token():
    """Return the CSRF token for the current session.

    Only used by the Vite dev server (localhost:3001), where the page is not
    rendered by Frappe and so has no window.csrf_token. In production the token
    is injected by www/planning-app.html.
    """
    return frappe.sessions.get_csrf_token()
