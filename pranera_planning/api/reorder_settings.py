"""API for the planning app's Re-order Settings page. Reads and saves the same single doctype
as the desk form (Re-order Settings), so both always show the same values; saving goes
through the doctype, so its permissions and validation apply."""
import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from pranera_planning.api.supplier_lead_days import supplier_lead_counts
from pranera_planning.lead_math import DEFAULT_ORDER, KEY_OF, LABELS, source_order

DOCTYPE = "Re-order Settings"
SCALARS = {
    "history_days": cint, "near_margin": flt, "default_safety_days": flt, "default_cover_days": flt,
    "default_round_to": flt, "lead_history_months": cint, "use_learned_lead_days": cint,
    "include_bought_lead_days": cint, "default_warehouse": str, "stock_project_period": str,
    "stock_project_pattern": str, "no_default_supplier": str, "lead_time_check": str, "lead_time_grace_days": cint,
}
TABLES = {
    "group_rules": ["item_group", "demand_basis", "safety_days", "cover_days", "round_to", "bought_lead_days"],
    # learned figures are filled nightly: kept from the saved rows, never taken from the page
    "stage_leads": ["stage", "route", "override_days", "job_work_services"],
    "seasons": ["season", "start_month"],
    "lead_sources": ["source", "enabled"],
}
LABEL_KEYS = set(KEY_OF)
LEARNED = ["inhouse_days", "inhouse_orders", "jobwork_days", "jobwork_orders"]


def _out(doc):
    return {
        **{k: doc.get(k) for k in SCALARS},
        "group_rules": [{f: r.get(f) for f in TABLES["group_rules"]} for r in doc.group_rules],
        "stage_leads": [{f: r.get(f) for f in TABLES["stage_leads"] + LEARNED} for r in doc.stage_leads],
        "seasons": [{f: r.get(f) for f in TABLES["seasons"]} for r in doc.seasons],
        "lead_sources": _lead_sources(doc),
        "supplier_lead_counts": supplier_lead_counts(),
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
            if table == "lead_sources":
                if values.get("source") not in LABEL_KEYS:
                    continue
                values["enabled"] = 1 if row.get("enabled") else 0
            doc.append(table, values)
    pattern = doc.get("stock_project_pattern") or ""
    if "{FAMILY}" not in pattern:
        frappe.throw(_("The project name must contain {FAMILY}, or every family would share one project."))
    sources = doc.get("lead_sources") or []
    if sources and not any(r.get("enabled") for r in sources):
        frappe.throw(_("Switch on at least one source for lead days, or no bought item would have any."))
    if doc.get("lead_time_grace_days") and doc.lead_time_grace_days < 0:
        frappe.throw(_("Grace days can't be negative."))
    doc.save()
    return _out(doc)


# ── supplier lead days ────────────────────────────────────────────────────────

def _lead_sources(doc):
    """The ranked sources; all four, always (any missing are added at the end, switched on)."""
    rows = [{"source": r.source, "enabled": cint(r.enabled)} for r in doc.get("lead_sources") or [] if r.source in LABEL_KEYS]
    have = {r["source"] for r in rows}
    return rows + [{"source": LABELS[k], "enabled": 1} for k in DEFAULT_ORDER if LABELS[k] not in have]


@frappe.whitelist()
def explain_lead(item, supplier=None, sources=None, no_default_supplier=None):
    """The settings page's Try an item box: every source's value for `item`, and which wins
    with the page's (maybe unsaved) ranking. Lead days themselves are read as saved."""
    frappe.has_permission(DOCTYPE, "read", throw=True)
    from pranera_planning.lead_time import group_days_for, resolve
    from pranera_planning.reorder import load_settings
    blank = (None, "", "null", "undefined")
    supplier = None if supplier in blank else supplier
    no_default_supplier = None if no_default_supplier in blank else no_default_supplier
    rows = json.loads(sources) if isinstance(sources, str) else (sources or [])
    cfg = load_settings()
    lead_cfg = dict(cfg["lead"])
    if rows:
        lead_cfg["order"] = source_order(rows)
    if no_default_supplier:
        lead_cfg["fallback"] = no_default_supplier
    it = frappe.db.get_value("Item", item, ["name", "item_group", "lead_time_days"], as_dict=True)
    if not it:
        frappe.throw(_("Item {0} not found.").format(item))
    res = resolve([item], {item: it}, group_days_for([it.item_group], cfg["rules"]), lead_cfg,
                  supplier=supplier or None, all_sources=True)[item]
    ranked = rows or [{"source": LABELS[k], "enabled": 1} for k in DEFAULT_ORDER]
    return {
        "item": item, "days": res["days"], "winner": res["source"] and LABELS[res["source"]],
        "supplier": res["supplier"], "text": res["text"],
        "supplier_from": "chosen above" if supplier else res["supplier_from"],
        "fallback": lead_cfg["fallback"], "months": lead_cfg["months"],
        "sources": [{"source": r["source"], "enabled": cint(r.get("enabled")),
                     "value": res["values"].get(KEY_OF.get(r["source"]))} for r in ranked if r.get("source") in LABEL_KEYS],
    }
