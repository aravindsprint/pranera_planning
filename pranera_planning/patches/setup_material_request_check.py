"""Purchase Material Request free-stock check: the override-reason field on Material Request,
and starting values for Stock Reservation Settings (Block; Purchase Manager may override).
Safe to run again: existing settings are left as they are."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Material Request": [{
            "fieldname": "reservation_override_reason",
            "label": "Override reason (buying despite free stock)",
            "fieldtype": "Small Text",
            "insert_after": "schedule_date",
            "depends_on": "eval:doc.material_request_type=='Purchase'",
            "description": "Only for users allowed to override the free-stock check in Stock Reservation Settings: "
                           "why this is bought although the same item is free in stores.",
            "no_copy": 1,
        }],
    }, update=True)

    settings = frappe.get_single("Stock Reservation Settings")
    changed = False
    if not settings.material_request_check:
        settings.material_request_check = "Block"
        changed = True
    if not settings.override_roles and frappe.db.exists("Role", "Purchase Manager"):
        settings.append("override_roles", {"role": "Purchase Manager"})
        changed = True
    if changed:
        settings.save(ignore_permissions=True)
