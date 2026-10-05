"""Lead days of bought items, by supplier. Reads the numbers; the ranking and date arithmetic
are in lead_math.py.

Where the numbers live (custom fields, patches/add_supplier_lead_days.py):
    Supplier.usual_lead_days          China supplier 45, Indian mills 15
    Item Supplier.lead_days           the item's Supplier Items row: melange from one mill 45
    Item.lead_time_days               standard field
    Re-order Group Rule.bought_lead_days

Which supplier an item is bought from: the Purchase Order's supplier when there is one;
otherwise the item's Default Supplier (Item Defaults), else — as Re-order Settings says — the
supplier of its latest Purchase Order, the one it was bought from most, or none.
"""
from collections import defaultdict

import frappe
from frappe.utils import add_months, flt, today

from pranera_planning.lead_math import (
    GROUP, ITEM, LATEST_PO, MOST_BOUGHT, NO_SUPPLIER, SUPPLIER, SUPPLIER_ITEM, describe, pick_lead, source_order,
)

CHUNK = 500


def _chunks(xs, n=CHUNK):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield tuple(xs[i:i + n])


def _has(doctype, field):
    try:
        return bool(frappe.db.has_column(doctype, field))
    except Exception:
        return False


def load_config(s):
    """The Supplier lead days part of Re-order Settings (the doc `s`)."""
    if s is None:
        return default_config()
    check = (s.get("lead_time_check") or "Block")
    return {
        "order": source_order(s.get("lead_sources") or []),
        "fallback": s.get("no_default_supplier") or LATEST_PO,
        "months": int(s.get("lead_history_months") or 6),
        "check": check if check in ("Off", "Warn", "Block") else "Block",
        "grace": flt(s.get("lead_time_grace_days")),
    }


def default_config():
    return {"order": source_order([]), "fallback": LATEST_PO, "months": 6, "check": "Block", "grace": 0.0}


def _company():
    try:
        return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
    except Exception:
        return None


def default_suppliers(items):
    """{item: Default Supplier} from Item Defaults (the user's company first)."""
    items = [i for i in items if i]
    if not items:
        return {}
    comp = _company()
    out, rank = {}, {}
    for r in frappe.get_all("Item Default", filters={"parent": ["in", items], "parenttype": "Item"},
                            fields=["parent", "default_supplier", "company"]):
        if not r.get("default_supplier"):
            continue
        score = 0 if comp and r.get("company") == comp else 1
        if r.parent not in out or score < rank[r.parent]:
            out[r.parent], rank[r.parent] = r.default_supplier, score
    return out


def fallback_suppliers(items, mode, months=6):
    """({item: supplier}, text) for items with no Default Supplier, by Re-order Settings'
    choice: the supplier of the latest submitted Purchase Order, or the one bought from most
    (by quantity) in the last `months`. Job-work (subcontracted) orders don't count."""
    items = [i for i in items if i]
    if not items or mode == NO_SUPPLIER:
        return {}, ""
    out = {}
    if mode == MOST_BOUGHT:
        since = add_months(today(), -int(months or 6))
        totals = defaultdict(lambda: defaultdict(float))
        for chunk in _chunks(items):
            for item, supplier, qty in frappe.db.sql(
                """SELECT poi.item_code, po.supplier, SUM(poi.stock_qty) FROM `tabPurchase Order Item` poi
                   JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
                    AND IFNULL(po.is_subcontracted, 0) = 0 AND po.transaction_date >= %(since)s
                   WHERE poi.item_code IN %(items)s GROUP BY poi.item_code, po.supplier""",
                    {"items": chunk, "since": since}):
                totals[item][supplier] += flt(qty)
        for item, by in totals.items():
            out[item] = max(sorted(by), key=lambda s: by[s])
        return out, f"bought most from in the last {int(months or 6)} months"
    for chunk in _chunks(items):
        for item, supplier in frappe.db.sql(
            """SELECT poi.item_code, po.supplier FROM `tabPurchase Order Item` poi
               JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
                AND IFNULL(po.is_subcontracted, 0) = 0
               WHERE poi.item_code IN %(items)s
               ORDER BY po.transaction_date DESC, po.creation DESC""", {"items": chunk}):
            out.setdefault(item, supplier)
    return out, "latest Purchase Order"


def supplier_days(suppliers):
    """{supplier: usual lead days}."""
    suppliers = [s for s in suppliers if s]
    if not suppliers or not _has("Supplier", "usual_lead_days"):
        return {}
    return {r.name: flt(r.usual_lead_days) for r in frappe.get_all(
        "Supplier", filters={"name": ["in", suppliers]}, fields=["name", "usual_lead_days"]) if flt(r.usual_lead_days) > 0}


def supplier_item_days(items):
    """{(item, supplier): lead days} from the items' Supplier Items rows."""
    items = [i for i in items if i]
    if not items or not _has("Item Supplier", "lead_days"):
        return {}
    return {(r.parent, r.supplier): flt(r.lead_days) for r in frappe.get_all(
        "Item Supplier", filters={"parent": ["in", items], "parenttype": "Item"},
        fields=["parent", "supplier", "lead_days"]) if r.get("supplier") and flt(r.lead_days) > 0}


def resolve(items, info, group_days, lead_cfg=None, supplier=None, all_sources=False):
    """{item: {"days", "source", "supplier", "supplier_from", "text", "values"}}.

    info        {item: {"item_group", "lead_time_days"}}
    group_days  item group -> the nearest rule's Lead days when bought (or 0)
    supplier    the Purchase Order's supplier; None = the item's usual supplier
    all_sources read every source even when switched off (for the settings page's Try box)"""
    cfg = lead_cfg or default_config()
    order = cfg["order"]
    items = [i for i in items if i]
    need = all_sources or SUPPLIER in order or SUPPLIER_ITEM in order
    sup_of, sup_from = {}, {}
    if need and items:
        if supplier:
            sup_of = {i: supplier for i in items}
            sup_from = {i: "this Purchase Order" for i in items}
        else:
            sup_of = default_suppliers(items)
            sup_from = {i: "default" for i in sup_of}
            missing = [i for i in items if i not in sup_of]
            if missing:
                more, text = fallback_suppliers(missing, cfg["fallback"], cfg["months"])
                sup_of.update(more)
                sup_from.update({i: text for i in more})
    s_days = supplier_days(set(sup_of.values())) if (all_sources or SUPPLIER in order) else {}
    r_days = supplier_item_days(items) if (all_sources or SUPPLIER_ITEM in order) else {}

    out = {}
    for code in items:
        it = info.get(code) or {}
        sup = sup_of.get(code)
        values = {
            SUPPLIER_ITEM: r_days.get((code, sup)) if sup else None,
            SUPPLIER: s_days.get(sup) if sup else None,
            ITEM: flt(it.get("lead_time_days")) or None,
            GROUP: flt(group_days(it.get("item_group"))) or None,
        }
        days, source = pick_lead(order, values)
        out[code] = {"days": days, "source": source, "supplier": sup, "supplier_from": sup_from.get(code),
                     "text": describe(days, source, sup, sup_from.get(code)), "values": values}
    return out


def group_days_for(item_groups, rules):
    """item group -> its nearest rule's bought_lead_days, for `rules` [(lft, rgt, rule)] as in
    reorder.load_settings."""
    from pranera_planning.reorder_math import deepest
    groups = [g for g in set(item_groups) if g]
    bounds = {g.name: (g.lft, g.rgt) for g in frappe.get_all(
        "Item Group", filters={"name": ["in", groups]}, fields=["name", "lft", "rgt"])} if groups else {}

    def days(group):
        rule = deepest(bounds.get(group), rules)
        return flt(rule.bought_lead_days) if rule else 0.0
    return days
