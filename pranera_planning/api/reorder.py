"""API for the Stock levels and re-order page. Reads Item Re-order Level (written by
reorder.py nightly / on Recalculate) — the page never recalculates the whole company itself."""
import json

import frappe
from frappe import _
from frappe.utils import flt

STATUS_ORDER = ["Order now", "Near", "OK", "Over max", "No demand"]
FIELDS = [
    "name", "item_name", "item_group", "family", "stage", "obtained", "stock_uom", "status",
    "demand_basis", "demand_qty", "avg_daily", "lead_days", "safety_days", "cover_days", "round_to",
    "safety_qty", "reorder_level", "reorder_qty", "max_level", "in_stores", "reserved", "free", "wip",
    "on_order", "position", "suggest_qty", "calculated_on",
    "supplier", "lead_source", "arriving_later", "arriving_later_note",
]


@frappe.whitelist()
def get_reorder_report(status=None, item_group=None, obtained=None, search=None, limit=500):
    """Rows of Item Re-order Level, Order now first (largest suggestion first), with the
    count per status for the chips (ignoring the status filter, so the chips always add up)
    and the settings the numbers came from."""
    frappe.has_permission("Item Re-order Level", "read", throw=True)
    base = {}
    if obtained in ("Made", "Bought"):
        base["obtained"] = obtained
    if item_group:
        bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
        if bounds:
            base["item_group"] = ["in", frappe.get_all(
                "Item Group", filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]}, pluck="name")]
    or_filters = None
    if search:
        like = f"%{search.strip()}%"
        or_filters = {"name": ["like", like], "item_name": ["like", like], "family": ["like", like]}

    counts = {s: 0 for s in STATUS_ORDER}
    for r in frappe.get_all("Item Re-order Level", filters=base, or_filters=or_filters,
                            fields=["status", "count(name) as n"], group_by="status"):
        counts[r.status or "No demand"] = r.n

    filters = dict(base)
    if status in STATUS_ORDER:
        filters["status"] = status
    rows = frappe.get_all("Item Re-order Level", filters=filters, or_filters=or_filters, fields=FIELDS,
                          limit_page_length=int(limit or 500))
    for r in rows:
        r["item_code"] = r.pop("name")
        r["lead_missing"] = flt(r.lead_days) <= 0 and (r.obtained == "Made" or flt(r.avg_daily) > 0)
    rank = {s: i for i, s in enumerate(STATUS_ORDER)}
    rows.sort(key=lambda r: (rank.get(r.status, 9), -flt(r.suggest_qty), r["item_code"]))

    s = frappe.get_single("Re-order Settings")
    return {
        "rows": rows,
        "counts": counts,
        "total": sum(counts.values()),
        "settings": {
            "history_days": s.history_days or 90,
            "near_margin": s.near_margin if s.near_margin is not None else 10,
            "last_run": s.last_run,
            "last_run_items": s.last_run_items,
            "stages_without_days": [r.stage for r in s.stage_leads if r.stage and not flt(r.override_days)
                                    and not (s.get("use_learned_lead_days") and (r.inhouse_days or r.jobwork_days))],
        },
    }


@frappe.whitelist(methods=["POST"])
def recalculate_items(items):
    """Recalculate a few items now (the page's per-row Refresh) — synchronous, so at most 50."""
    frappe.only_for(("System Manager", "Stock Manager", "Manufacturing Manager", "Purchase Manager"))
    if isinstance(items, str):
        items = json.loads(items or "[]")
    items = [i for i in (items or []) if i][:50]
    if not items:
        frappe.throw(_("No items to recalculate."))
    from pranera_planning.reorder import calculate, load_settings
    count = calculate(items, load_settings())
    return count
