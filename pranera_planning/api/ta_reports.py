"""API for the planning app's T&A Reports page (ta_reports.py does the work)."""
import frappe

from pranera_planning import ta_reports

PLAN = "Time and Action Plan"


@frappe.whitelist()
def dashboard(stage=None, customer=None):
    frappe.has_permission(PLAN, "read", throw=True)
    return ta_reports.dashboard(stage or None, customer or None)


@frappe.whitelist()
def utilisation(stage=None, start=None, weeks=8):
    frappe.has_permission(PLAN, "read", throw=True)
    return ta_reports.utilisation(stage or None, start or None, weeks)


@frappe.whitelist()
def delays(from_date=None, to_date=None, stage=None):
    frappe.has_permission(PLAN, "read", throw=True)
    return ta_reports.delays(from_date or None, to_date or None, stage or None)
