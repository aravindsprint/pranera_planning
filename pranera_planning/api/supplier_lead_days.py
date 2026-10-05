"""API for the planning app's Supplier lead days page: every supplier's usual lead days
(Supplier.usual_lead_days) and the exceptions for one item from one supplier (the Item's
Supplier Items rows, Item Supplier.lead_days). The page edits those fields directly, so desk
and app always show the same numbers. Which of them counts, and in what order, is set in
Re-order Settings (lead_time.py)."""
import json

import frappe
from frappe import _
from frappe.utils import cint


def _ready():
    return frappe.db.has_column("Supplier", "usual_lead_days") and frappe.db.has_column("Item Supplier", "lead_days")


def supplier_lead_rows():
    """{"supplier_leads": [{supplier, usual_lead_days}], "item_supplier_leads": [{item_code, supplier, lead_days}],
    "lead_fields_ready"} — every supplier and Supplier Items row with lead days set."""
    if not _ready():
        return {"supplier_leads": [], "item_supplier_leads": [], "lead_fields_ready": False}
    return {
        "supplier_leads": [{"supplier": r.name, "usual_lead_days": cint(r.usual_lead_days)} for r in frappe.get_all(
            "Supplier", filters={"usual_lead_days": [">", 0]}, fields=["name", "usual_lead_days"], order_by="name")],
        "item_supplier_leads": [{"item_code": r.parent, "supplier": r.supplier, "lead_days": cint(r.lead_days)}
                                for r in frappe.get_all("Item Supplier", filters={"parenttype": "Item", "lead_days": [">", 0]},
                                                        fields=["parent", "supplier", "lead_days"], order_by="parent, supplier")],
        "lead_fields_ready": True,
    }


def _save(data):
    """Write the page's two lead-day tables to the Supplier and Item Supplier fields: changed
    numbers are set, rows taken off the page are cleared (the Supplier Items row itself stays,
    as it may carry a part number)."""
    if "supplier_leads" not in data and "item_supplier_leads" not in data:
        return
    if not _ready():
        frappe.throw(_("The supplier lead day fields aren't installed yet: run bench migrate."))
    now = supplier_lead_rows()

    if "supplier_leads" in data:
        want = {}
        for r in data.get("supplier_leads") or []:
            if r.get("supplier") and cint(r.get("usual_lead_days")) > 0:
                want[r["supplier"]] = cint(r["usual_lead_days"])
        have = {r["supplier"]: r["usual_lead_days"] for r in now["supplier_leads"]}
        for supplier in set(want) | set(have):
            if want.get(supplier, 0) != have.get(supplier, 0):
                frappe.has_permission("Supplier", "write", supplier, throw=True)
                frappe.db.set_value("Supplier", supplier, "usual_lead_days", want.get(supplier) or 0)

    if "item_supplier_leads" in data:
        want = {}
        for r in data.get("item_supplier_leads") or []:
            if r.get("item_code") and r.get("supplier") and cint(r.get("lead_days")) > 0:
                want[(r["item_code"], r["supplier"])] = cint(r["lead_days"])
        have = {(r["item_code"], r["supplier"]): r["lead_days"] for r in now["item_supplier_leads"]}
        for item, supplier in set(want) | set(have):
            days = want.get((item, supplier), 0)
            if days == have.get((item, supplier), 0):
                continue
            frappe.has_permission("Item", "write", item, throw=True)
            row = frappe.db.get_value("Item Supplier", {"parent": item, "parenttype": "Item", "supplier": supplier}, "name")
            if row:
                frappe.db.set_value("Item Supplier", row, "lead_days", days)
            elif days:
                it = frappe.get_doc("Item", item)
                it.append("supplier_items", {"supplier": supplier, "lead_days": days})
                it.save()


def supplier_lead_counts():
    """{"suppliers", "items"}: how many have lead days set, for the Re-order Settings page."""
    if not _ready():
        return {"suppliers": 0, "items": 0, "ready": False}
    return {"suppliers": len(frappe.get_all("Supplier", filters={"usual_lead_days": [">", 0]}, pluck="name")),
            "items": len(frappe.get_all("Item Supplier", filters={"parenttype": "Item", "lead_days": [">", 0]}, pluck="name")),
            "ready": True}


def _can_write():
    return bool(frappe.has_permission("Supplier", "write") or frappe.has_permission("Item", "write"))


@frappe.whitelist()
def get_lead_days():
    frappe.has_permission("Supplier", "read", throw=True)
    return {**supplier_lead_rows(), "can_write": _can_write()}


@frappe.whitelist(methods=["POST"])
def save_lead_days(data):
    data = json.loads(data) if isinstance(data, str) else (data or {})
    _save(data)
    return {**supplier_lead_rows(), "can_write": _can_write()}
