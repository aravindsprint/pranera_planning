"""API for the planning app's Re-order Settings page. Reads and saves the same single doctype
as the desk form (Re-order Settings), so both always show the same values; saving goes
through the doctype, so its permissions and validation apply."""
import json

import frappe
from frappe import _
from frappe.utils import cint, flt

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
        **supplier_lead_rows(),
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
    save_supplier_leads(data)
    doc.save()
    return _out(doc)


# ── supplier lead days ────────────────────────────────────────────────────────

def _lead_sources(doc):
    """The ranked sources; all four, always (any missing are added at the end, switched on)."""
    rows = [{"source": r.source, "enabled": cint(r.enabled)} for r in doc.get("lead_sources") or [] if r.source in LABEL_KEYS]
    have = {r["source"] for r in rows}
    return rows + [{"source": LABELS[k], "enabled": 1} for k in DEFAULT_ORDER if LABELS[k] not in have]


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


def save_supplier_leads(data):
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


@frappe.whitelist()
def explain_lead(item, supplier=None, sources=None, no_default_supplier=None):
    """The settings page's Try an item box: every source's value for `item`, and which wins
    with the page's (maybe unsaved) ranking. Lead days themselves are read as saved."""
    frappe.has_permission(DOCTYPE, "read", throw=True)
    from pranera_planning.lead_time import group_days_for, resolve
    from pranera_planning.reorder import load_settings
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
        "supplier": res["supplier"], "supplier_from": res["supplier_from"], "text": res["text"],
        "sources": [{"source": r["source"], "enabled": cint(r.get("enabled")),
                     "value": res["values"].get(KEY_OF.get(r["source"]))} for r in ranked if r.get("source") in LABEL_KEYS],
    }
