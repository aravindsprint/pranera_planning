"""Workstation "Disabled": a machine no longer in use. ERPNext's Workstation has no such field
(its Status is the machine's state on the shop floor). The planning app already leaves out a
disabled workstation: it is not on the Workstation Board and nothing can be booked on it."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Workstation": [
            {"fieldname": "disabled", "label": "Disabled", "fieldtype": "Check", "default": "0",
             "insert_after": "workstation_name", "in_standard_filter": 1,
             "description": "No longer in use: left off the Workstation Board and can't be booked."},
        ],
    }, update=True)
