"""API for the Project Planning page's Time & Action tab (ta.py does the work)."""
import frappe

from pranera_planning import ta


@frappe.whitelist()
def get_ta(project):
    frappe.has_permission("Project", "read", project, throw=True)
    return ta.view(project)


@frappe.whitelist(methods=["POST"])
def rebuild_ta(project):
    frappe.has_permission("Project", "write", project, throw=True)
    ta.rebuild(project)
    return ta.view(project)


@frappe.whitelist(methods=["POST"])
def save_ta(project, rows):
    frappe.has_permission("Project", "read", project, throw=True)
    return ta.save(project, rows)
