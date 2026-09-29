"""WIP and subcontractor warehouses are now recognised by how Work Orders / Subcontracting
Orders use them, not only by name. Stock there is already committed to an order, so an
Active reservation sitting in one reserves stock twice — release it, with a remark."""
import frappe
from frappe.utils import now_datetime

from pranera_planning.reservation import clear_warehouse_cache, warehouse_place


def execute():
    clear_warehouse_cache()
    for r in frappe.get_all("Project Stock Reservation", filters={"status": "Active"}, fields=["name", "warehouse", "remarks"]):
        place = warehouse_place(r.warehouse)
        if not place:
            continue
        note = f"Released by migration: {r.warehouse} is a {place.lower()} warehouse, not stores — its stock is already committed to an order."
        frappe.db.set_value("Project Stock Reservation", r.name, {
            "status": "Released",
            "released_on": now_datetime(),
            "remarks": "\n".join(p for p in (r.remarks, note) if p),
        }, update_modified=False)
