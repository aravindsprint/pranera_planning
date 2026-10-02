"""API for the planning app's Re-order Settings page. Reads and saves the same single doctype
as the desk form (Re-order Settings), so both always show the same values; saving goes
through the doctype, so its permissions and validation apply."""
import json

import frappe
from frappe import _
from frappe.utils import cint, flt

DOCTYPE = "Re-order Settings"
SCALARS = {
    "history_days": cint, "near_margin": flt, "default_safety_days": flt, "default_cover_days": flt,
    "default_round_to": flt, "lead_history_months": cint, "use_learned_lead_days": cint,
    "include_bought_lead_days": cint, "default_warehouse": str, "stock_project_period": str,
    "stock_project_pattern": str,
}
TABLES = {
    "group_rules": ["item_group", "demand_basis", "safety_days", "cover_days", "round_to", "bought_lead_days"],
    # learned figures are filled nightly: kept from the saved rows, never taken from the page
    "stage_leads": ["stage", "route", "override_days", "job_work_services"],
    "seasons": ["season", "start_month"],
}
LEARNED = ["inhouse_days", "inhouse_orders", "jobwork_days", "jobwork_orders"]


def _out(doc):
    return {
        **{k: doc.get(k) for k in SCALARS},
        "group_rules": [{f: r.get(f) for f in TABLES["group_rules"]} for r in doc.group_rules],
        "stage_leads": [{f: r.get(f) for f in TABLES["stage_leads"] + LEARNED} for r in doc.stage_leads],
        "seasons": [{f: r.get(f) for f in TABLES["seasons"]} for r in doc.seasons],
        "last_run": doc.get("last_run"),
        "last_run_items": doc.get("last_run_items"),
        "can_write": bool(frappe.has_permission(DOCTYPE, "write")),
    }


@frappe.whitelist()
def get_settings():
    frappe.has_permission(DOCTYPE, "read", throw=True)
    return _out(frappe.get_single(DOCTYPE))


@frappe.whitelist(methods=["POST"])
def save_settings(settings):
    frappe.has_permission(DOCTYPE, "write", throw=True)
    data = json.loads(settings) if isinstance(settings, str) else settings
    doc = frappe.get_single(DOCTYPE)
    for field, cast in SCALARS.items():
        if field in data:
            value = data[field]
            doc.set(field, (value or None) if cast is str else cast(value or 0))

    learned = {(r.stage or "").strip().lower(): {f: r.get(f) for f in LEARNED} for r in doc.stage_leads}
    for table, fields in TABLES.items():
        if table not in data:
            continue
        doc.set(table, [])
        for row in data[table] or []:
            values = {f: row.get(f) for f in fields if row.get(f) not in (None, "")}
            if table == "group_rules" and not values.get("item_group"):
                continue
            if table == "stage_leads":
                if not values.get("stage"):
                    continue
                values.update(learned.get(values["stage"].strip().lower(), {}))
            if table == "seasons" and not (values.get("season") and values.get("start_month")):
                continue
            doc.append(table, values)
    pattern = doc.get("stock_project_pattern") or ""
    if "{FAMILY}" not in pattern:
        frappe.throw(_("The project name must contain {FAMILY}, or every family would share one project."))
    doc.save()
    return _out(doc)
