"""Supplier lead days: where they are entered (Supplier, the Item's Supplier Items rows), the
Purchase Order's override reason, and starting values in Re-order Settings — every source
on in the default order, latest Purchase Order for items with no default supplier, and the
Purchase Order check on Block with no grace days. Nothing changes until lead days are
entered. Safe to run again: existing values are left as they are."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from pranera_planning.lead_math import DEFAULT_ORDER, LABELS


def execute():
    for name in ("re_order_lead_source", "re_order_settings", "item_re_order_level"):
        frappe.reload_doc("planning", "doctype", name, force=True)
    create_custom_fields({
        "Supplier": [{
            "fieldname": "usual_lead_days", "label": "Usual lead days", "fieldtype": "Int",
            "insert_after": "supplier_group", "non_negative": 1,
            "description": "Days from order to delivery, usually. Re-order levels and the Purchase Order "
                           "lead time check use it; an item's own Supplier Items row comes first.",
        }],
        "Item Supplier": [{
            "fieldname": "lead_days", "label": "Lead days", "fieldtype": "Int", "insert_after": "supplier_part_no",
            "in_list_view": 1, "columns": 1, "non_negative": 1,
            "description": "This item from this supplier, when it differs from the supplier's usual lead days.",
        }],
        "Purchase Order": [{
            "fieldname": "lead_time_override_reason", "label": "Lead time override reason", "fieldtype": "Small Text",
            "insert_after": "schedule_date", "no_copy": 1, "allow_on_submit": 1,
            "description": "Only for users allowed to override (Stock Reservation Settings): why a Required By "
                           "earlier than the supplier's lead days is accepted, e.g. air freight or a confirmed date.",
        }],
    }, update=True)

    s = frappe.get_single("Re-order Settings")
    if not s.get("lead_sources"):
        for key in DEFAULT_ORDER:
            s.append("lead_sources", {"source": LABELS[key], "enabled": 1})
    for field, value in (("no_default_supplier", "Latest Purchase Order"), ("lead_time_check", "Block")):
        if not s.get(field):
            s.set(field, value)
    s.flags.ignore_permissions = True
    s.save()
