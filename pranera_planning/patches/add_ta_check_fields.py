"""T&A override reason on Work Order and Job Card, for the workstation and input checks."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    frappe.reload_doc("planning", "doctype", "re_order_settings", force=True)
    field = {"fieldname": "ta_override_reason", "label": "T&A override reason", "fieldtype": "Small Text", "no_copy": 1,
             "allow_on_submit": 1,
             "description": "Only for users allowed to override (Stock Reservation Settings): why this machine or this "
                            "early start is accepted although the Time and Action plan says otherwise."}
    create_custom_fields({"Work Order": [{**field, "insert_after": "project"}],
                          "Job Card": [{**field, "insert_after": "workstation"}]}, update=True)
