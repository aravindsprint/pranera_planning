"""Made-to-stock projects get a sequence: a site still on the old default name pattern moves to
"{YY}STK-{FAMILY}-{PERIOD}-{SEQ}", so a second plan for a family in the same period gets its own
project (…-Q4-02). A pattern someone changed is left alone."""
import frappe


def execute():
    frappe.reload_doc("planning", "doctype", "re_order_settings", force=True)
    current = frappe.db.get_single_value("Re-order Settings", "stock_project_pattern")
    if not current or current.strip() == "{YY}STK-{FAMILY}-{PERIOD}":
        frappe.db.set_single_value("Re-order Settings", "stock_project_pattern", "{YY}STK-{FAMILY}-{PERIOD}-{SEQ}")
