"""Workstation "Disabled": a machine no longer in use. The planning app leaves a disabled
workstation out: it is not on the Workstation Board and nothing can be booked on it.

ERPNext v15's Workstation has no such field (its Status is the machine's state on the shop
floor), so it is added as a custom field. ERPNext v16 has a standard `disabled` field with the
same name (it also sets Status to Off): there the custom field is not added, and one added
under v15 is removed — the column and its values stay, the standard field takes them over.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM = "Workstation-disabled"


def standard_field_exists():
    return bool(frappe.db.exists("DocField", {"parent": "Workstation", "fieldname": "disabled"}))


def drop_if_standard():
    """after_migrate hook: on ERPNext v16 the standard field replaces the custom one (a patch
    runs once, so it would not see a later upgrade)."""
    if standard_field_exists() and frappe.db.exists("Custom Field", CUSTOM):
        frappe.db.delete("Custom Field", {"name": CUSTOM})          # keep the column and its values
        frappe.clear_cache(doctype="Workstation")


def execute():
    if standard_field_exists():
        drop_if_standard()
        return
    create_custom_fields({
        "Workstation": [
            {"fieldname": "disabled", "label": "Disabled", "fieldtype": "Check", "default": "0",
             "insert_after": "workstation_name", "in_standard_filter": 1,
             "description": "No longer in use: left off the Workstation Board and can't be booked."},
        ],
    }, update=True)
