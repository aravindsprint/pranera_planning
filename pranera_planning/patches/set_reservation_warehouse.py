"""Reservations are now held at warehouse + batch (+ roll for fabric / collar / cuff).

Existing Active reservations were batch-wide. Where that maps onto exactly one location —
a yarn / batch item whose stock sits in a single issuable warehouse — the warehouse is filled
in. Anything else can't be placed without guessing, so it is released with a remark saying
why; re-reserve it from the Stock Reservation page.
"""
import frappe
from frappe.utils import now_datetime

from pranera_planning.reservation import get_stock_locations, roll_tracked_items


def execute():
    rows = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Active", "warehouse": ["in", ["", None]]},
        fields=["name", "item_code", "batch_no", "remarks"],
    )
    if not rows:
        return

    locations = get_stock_locations(list({r.batch_no for r in rows}))
    roll_items = roll_tracked_items([r.item_code for r in rows])

    for r in rows:
        stocked = [wh for wh, loc in locations.get(r.batch_no, {}).items() if loc["available"] > 1e-6]
        if r.item_code not in roll_items and len(stocked) == 1:
            frappe.db.set_value("Project Stock Reservation", r.name, "warehouse", stocked[0], update_modified=False)
            continue

        why = (
            "roll item — needs a roll no." if r.item_code in roll_items
            else f"batch is in {len(stocked)} warehouses" if stocked
            else "batch has no stock in stores"
        )
        note = f"Released by migration to warehouse-level reservations ({why}). Re-reserve from the Stock Reservation page."
        frappe.db.set_value("Project Stock Reservation", r.name, {
            "status": "Released",
            "released_on": now_datetime(),
            "remarks": "\n".join(p for p in (r.remarks, note) if p),
        }, update_modified=False)
