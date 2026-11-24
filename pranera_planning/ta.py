"""Time and Action plans: one per project (orders and stock programmes), built from the
project's plan and tracked against the documents. Scheduling and status rules: ta_math.py.

Built      on Create in the Plan tab (planner._create_one), or by Rebuild from plan.
Actuals    read when the plan is shown, never typed in for stages:
             In-house stage   its Work Orders under the project: first actual start, produced
                              qty, last actual end
             Job-work stage   its subcontracting Purchase Orders (start) and Subcontracting
                              Receipts (qty, end)
             Bought item      its Purchase Orders (start) and Purchase Receipts (qty, end)
           Milestones (lab dip, PP sample, dispatch …) are added and closed by hand.
"""
import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, today

from pranera_planning import ta_math

DOCTYPE = "Time and Action Plan"


def _has(doctype, field):
    try:
        return bool(frappe.db.has_column(doctype, field))
    except Exception:
        return False


def _plain(row):
    keys = ("seq", "activity", "kind", "stage", "item_code", "item_name", "qty", "uom", "route", "supplier", "service",
            "workstation", "duration_days", "planned_start", "planned_end", "baseline_end", "actual_start",
            "actual_end", "source", "remarks", "name")
    return {k: (str(row.get(k)) if k.startswith(("planned_", "actual_", "baseline_")) and row.get(k) else row.get(k))
            for k in keys}


# ── building ─────────────────────────────────────────────────────────────────

def deliver_on(project, prop):
    """The date the plan works back from: the Sales Order's delivery date for an order, else
    the plan's Needed by."""
    so = prop.get("sales_order") or frappe.db.get_value("Project", project, "sales_order")
    if so:
        d = frappe.db.get_value("Sales Order", so, "delivery_date")
        if d:
            return getdate(d)
    return getdate(prop.get("needed_by") or today())


def build_from_proposal(project, prop):
    """Create or rebuild the project's T&A plan from a plan proposal (its levels)."""
    order_type = prop.get("order_type") or ""
    final = _("Ready to deliver") if order_type != "Made to stock" else _("Stock at level")
    new = ta_math.schedule(prop.get("levels") or [], deliver_on(project, prop), final)
    name = frappe.db.exists(DOCTYPE, {"project": project})
    doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
    old = [_plain(r) for r in doc.get("activities") or []]
    for a in old:                                       # stage starts aren't stored: read them
        if a.get("source") == "plan" and a.get("kind") != ta_math.MILESTONE and not a.get("actual_start"):
            a["actual_start"] = actual_for(project, a).get("start")
    merged = ta_math.merge(old, new)
    p = frappe.db.get_value("Project", project, ["sales_order", "customer"], as_dict=True) or {}
    doc.update({"project": project, "order_type": order_type, "sales_order": p.get("sales_order"),
                "customer": p.get("customer"), "deliver_on": deliver_on(project, prop), "generated_on": now_datetime()})
    doc.set("activities", [])
    for a in merged:
        row = {k: v for k, v in a.items() if k != "name" and v not in (None, "")}
        if row.get("source") == "plan" and row.get("kind") != ta_math.MILESTONE:
            row.pop("actual_start", None)                 # read from the documents, never stored
            row.pop("actual_end", None)
        doc.append("activities", row)
    doc.flags.ignore_permissions = True
    doc.save() if name else doc.insert()
    return doc.name


def rebuild(project):
    """Rebuild from the project's saved plan, without creating anything."""
    from pranera_planning import planner
    from pranera_planning.api.project_planning import order_type_of, project_info, saved_plan
    p = project_info(project)
    plan = saved_plan(p)
    order_type = order_type_of(p)
    lines = [{"item": ln["item"], "qty": flt(ln.get("qty")), "mode": ln.get("mode")}
             for ln in plan.get("lines") or [] if ln.get("item") and flt(ln.get("qty")) > 0]
    if not lines:
        frappe.throw(_("{0} has no saved plan yet: plan it in the Plan tab first.").format(project))
    prop = planner.propose({"order_type": order_type, "project": project, "sales_order": p.get("sales_order"),
                            "needed_by": plan.get("needed_by"), "lines": lines})[0]
    return build_from_proposal(project, prop)


# ── actuals ──────────────────────────────────────────────────────────────────

def _one(sql, args):
    try:
        rows = frappe.db.sql(sql, args)
        return rows[0] if rows else (None, None, None)
    except Exception:
        frappe.log_error(title="T&A actuals query failed")
        return (None, None, None)


# Who the submitted Purchase Orders went to; the plan's supplier was only a proposal.
SUPPLIERS = "GROUP_CONCAT(DISTINCT po.supplier ORDER BY po.supplier SEPARATOR ', ')"


def actual_for(project, act):
    """{"start", "end", "done_qty"} for one activity, from the project's documents."""
    item, kind, route = act.get("item_code"), act.get("kind"), act.get("route")
    if not item or kind == ta_math.MILESTONE:
        return {}
    a = {"item": item, "project": project}
    supplier = None
    if kind == ta_math.STAGE and route != "Job work":
        start, end, qty = _one("""SELECT MIN(actual_start_date), MAX(actual_end_date), SUM(produced_qty)
            FROM `tabWork Order` WHERE production_item = %(item)s AND project = %(project)s AND docstatus = 1""", a)
    elif kind == ta_math.STAGE:
        fg = "poi.fg_item" if _has("Purchase Order Item", "fg_item") else "poi.item_code"
        start, supplier, _x = _one(f"""SELECT MIN(po.transaction_date), {SUPPLIERS}, NULL FROM `tabPurchase Order Item` poi
            JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1 AND IFNULL(po.is_subcontracted, 0) = 1
            WHERE {fg} = %(item)s AND poi.project = %(project)s""", a)
        on = "sri.project" if _has("Subcontracting Receipt Item", "project") else "sr.project"
        end, qty, _x = _one(f"""SELECT MAX(sr.posting_date), SUM(sri.qty), NULL FROM `tabSubcontracting Receipt Item` sri
            JOIN `tabSubcontracting Receipt` sr ON sr.name = sri.parent AND sr.docstatus = 1
            WHERE sri.item_code = %(item)s AND {on} = %(project)s""", a)
    else:
        start, supplier, _x = _one(f"""SELECT MIN(po.transaction_date), {SUPPLIERS}, NULL FROM `tabPurchase Order Item` poi
            JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1 AND IFNULL(po.is_subcontracted, 0) = 0
            WHERE poi.item_code = %(item)s AND poi.project = %(project)s""", a)
        end, qty, _x = _one("""SELECT MAX(pr.posting_date), SUM(pri.stock_qty), NULL FROM `tabPurchase Receipt Item` pri
            JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
            WHERE pri.item_code = %(item)s AND pri.project = %(project)s""", a)
    if qty and not start:
        start = end
    out = {"start": start, "end": end, "done_qty": flt(qty)}
    if supplier:
        out["supplier"] = supplier
    return out


def view(project):
    """The plan with every activity's status, for the Time & Action tab."""
    name = frappe.db.exists(DOCTYPE, {"project": project})
    if not name:
        return {"exists": False, "project": project, "rows": [], "summary": None}
    doc = frappe.get_doc(DOCTYPE, name)
    on = today()
    rows = []
    for r in doc.activities:
        a = _plain(r)
        actual = actual_for(project, a)
        st = ta_math.status_of(a, actual, on)
        if actual.get("supplier"):
            # the order decides who supplies; keep the planned one for comparison
            st["planned_supplier"] = a.get("supplier")
            st["supplier"] = actual["supplier"]
        if a.get("kind") == ta_math.MILESTONE:
            st["actual_start"] = a.get("actual_start") or st["actual_start"]
        rows.append({**a, **st})
    try:
        from pranera_planning.material_ready import readiness
        ready = readiness([{**r, "project": project} for r in rows
                           if r.get("kind") == ta_math.STAGE and r.get("status") != ta_math.DONE and r.get("name")])
    except Exception:
        frappe.log_error(title="Material readiness failed")
        ready = {}
    for r in rows:
        r["material"] = ready.get(r.get("name"))
    return {"exists": True, "project": project, "name": doc.name, "order_type": doc.order_type,
            "deliver_on": str(doc.deliver_on) if doc.deliver_on else None,
            "generated_on": str(doc.generated_on) if doc.generated_on else None,
            "today": str(on), "rows": rows, "summary": ta_math.summary(rows, on)}


# ── editing ──────────────────────────────────────────────────────────────────

EDITABLE = ("planned_start", "planned_end", "remarks", "workstation", "supplier", "actual_start", "actual_end", "activity")


def save(project, rows):
    """Save the tab's edits: planned dates, remarks, who does it, milestones (added, closed,
    removed). Plan activities can't be removed (rebuild the plan instead) and their actual
    dates come from the documents."""
    name = frappe.db.exists(DOCTYPE, {"project": project})
    if not name:
        frappe.throw(_("{0} has no Time and Action plan yet.").format(project))
    doc = frappe.get_doc(DOCTYPE, name)
    frappe.has_permission(DOCTYPE, "write", doc, throw=True)
    rows = json.loads(rows) if isinstance(rows, str) else rows
    by_name = {r.name: r for r in doc.activities}
    keep = []
    for r in rows:
        ps, pe = r.get("planned_start"), r.get("planned_end")
        if ps and pe and getdate(pe) < getdate(ps):
            frappe.throw(_("{0}: the planned end can't be before the planned start.").format(r.get("activity") or ""))
        if "planned_supplier" in r:
            # the shown supplier came from the Purchase Orders; store what the plan had
            r = {**r, "supplier": r.get("planned_supplier")}
        cur = by_name.get(r.get("name"))
        if cur:
            for k in EDITABLE:
                if k in ("actual_start", "actual_end") and cur.source == "plan" and cur.kind != ta_math.MILESTONE:
                    continue
                if k == "activity" and cur.source == "plan":
                    continue
                cur.set(k, r.get(k) or None)
            if ps and pe:
                cur.duration_days = max(0, (getdate(pe) - getdate(ps)).days)
            keep.append(cur)
        else:
            if not (r.get("activity") and pe):
                frappe.throw(_("A new milestone needs a name and a planned date."))
            keep.append(frappe._dict({"activity": r["activity"], "kind": ta_math.MILESTONE, "source": "manual",
                                      "planned_start": ps or pe, "planned_end": pe, "baseline_end": pe,
                                      "actual_end": r.get("actual_end") or None, "remarks": r.get("remarks")}))
    removed = [r for r in doc.activities if r.source == "plan" and r.name not in {getattr(k, "name", None) for k in keep}]
    if removed:
        frappe.throw(_("Plan activities can't be removed here ({0}): change the plan and rebuild instead.")
                     .format(", ".join(r.activity for r in removed)))
    keep.sort(key=lambda r: (str(r.get("planned_end") or "9999"), r.get("kind") == ta_math.MILESTONE))
    doc.set("activities", [])
    for i, r in enumerate(keep, 1):
        d = {k: r.get(k) for k in ("activity", "kind", "stage", "item_code", "item_name", "qty", "uom", "route", "supplier",
                                    "service", "workstation", "duration_days", "planned_start", "planned_end",
                                    "baseline_end", "actual_start", "actual_end", "source", "remarks")}
        doc.append("activities", {**{k: v for k, v in d.items() if v not in (None, "")}, "seq": i})
    doc.save()
    return view(project)
