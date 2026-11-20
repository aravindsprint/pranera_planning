"""Workstation "Output per operation": a machine's speed for each operation it runs, when it
differs from its Output per hour — a flat knitting machine makes 40 collars or 80 cuffs an hour.
The Workstation Board takes an item's operations from its default BOM."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    frappe.reload_doc("planning", "doctype", "workstation_operation_output", force=True)
    create_custom_fields({
        "Workstation": [
            {"fieldname": "operation_outputs", "label": "Output per operation", "fieldtype": "Table",
             "options": "Workstation Operation Output", "insert_after": "planning_uom",
             "description": "When the machine's speed depends on what it makes (collar or cuff): output per hour "
                            "for each operation of the item's default BOM. Other items use Output per hour."},
        ],
    }, update=True)
