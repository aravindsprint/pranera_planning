"""API for the Project Planning page's Overview tab: the project's order (made to order) or
stock programme (made to stock), its open requests, and its stages with what is planned.
Reads only; the Plan and Stock & reservations tabs use api.plan and api.reservation."""
import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from pranera_planning import planner
from pranera_planning.reservation import EPS, get_reservation_state, project_sco_items, same_project, stage_label

MTS, MTO = planner.MTS, planner.MTO


def order_type_of(p):
    """A project's order type: its Order type field, else made to order (a chosen project is planned for itself)."""
    return p.get("planning_order_type") or MTO


def saved_plan(p):
    try:
        return json.loads(p.get("saved_plan") or "{}") or {}
    except ValueError:
        return {}


def project_info(project):
    fields = ["name", "project_name", "project_type", "status", "customer", "sales_order"]
    fields += [f for f in ("planning_order_type", "stock_family", "stock_period", "saved_plan") if planner._has("Project", f)]
    p = frappe.db.get_value("Project", project, fields, as_dict=True)
    if not p:
        frappe.throw(_("Project {0} not found.").format(project))
    return p


def sales_order_lines(sales_order):
    """[{item, item_name, ordered, delivered, uom, label}] in stock units."""
    out = []
    for r in frappe.get_all("Sales Order Item", filters={"parent": sales_order},
                            fields=["item_code", "item_name", "qty", "delivered_qty", "conversion_factor", "stock_uom", "idx"],
                            order_by="idx"):
        cf = flt(r.conversion_factor) or 1
        out.append({"item": r.item_code, "item_name": r.item_name, "ordered": flt(r.qty) * cf,
                    "delivered": flt(r.delivered_qty) * cf, "uom": r.stock_uom, "label": _("line {0}").format(r.idx)})
    return out


def _remaining(rows):
    """{reservation name: remaining} for reservation rows that carry batch_no."""
    if not rows:
        return {}
    return {x["name"]: x["remaining_qty"] for st in get_reservation_state({r.batch_no for r in rows}).values()
            for x in st["reservations"]}


def _open_items(project):
    """Items in the project's open requests and orders (for the stages' Planned column)."""
    items = set(frappe.db.sql_list("""SELECT DISTINCT mri.item_code FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus < 2 WHERE mri.project = %s""", project))
    items |= set(frappe.db.sql_list("""SELECT DISTINCT production_item FROM `tabWork Order`
        WHERE docstatus = 1 AND project = %s""", project))
    sco_items = project_sco_items(project)
    if sco_items:
        items |= set(frappe.db.sql_list("""SELECT DISTINCT soi.item_code FROM `tabSubcontracting Order Item` soi
            JOIN `tabSubcontracting Order` sco ON sco.name = soi.parent AND sco.docstatus = 1
            WHERE soi.name IN %(i)s""", {"i": sco_items}))
    return items


@frappe.whitelist()
def get_overview(project):
    frappe.has_permission("Project", "read", project, throw=True)
    p = project_info(project)
    order_type = order_type_of(p)
    plan = saved_plan(p)

    # ── the panel: order lines, or stock-programme targets ─────────────────────
    if order_type == MTO:
        lines = sales_order_lines(p.sales_order) if p.sales_order else [
            {"item": ln["item"], "item_name": None, "ordered": flt(ln["qty"]), "delivered": 0.0, "uom": None,
             "label": _("planned")} for ln in plan.get("lines", [])]
    else:
        lines = [{"item": ln["item"], "target": flt(ln["qty"]), "mode": ln.get("mode") or "top_up"} for ln in plan.get("lines", [])]
    items = list({ln["item"] for ln in lines})
    info = planner.item_info(items)
    lots = planner.free_lots(items) if items else {}
    own_free = defaultdict(float)
    for item, ls in lots.items():
        for lot in ls:
            if lot["project"] and same_project(lot["project"], project):
                own_free[item] += lot["qty"]
    held = planner.held_for(project, items) if items else {}
    coming, _src = planner.coming(project, items) if items else ({}, {})

    rows = []
    if order_type == MTO:
        for ln in lines:
            item = ln["item"]
            to_go = max(0.0, ln["ordered"] - ln["delivered"])
            ready = min(to_go, own_free[item] + flt(held.get(item)))
            in_prod = min(max(0.0, to_go - ready), flt(coming.get(item)))
            rows.append({**ln, "item_name": ln.get("item_name") or (info.get(item) or {}).get("item_name"),
                         "uom": ln.get("uom") or (info.get(item) or {}).get("stock_uom"),
                         "ready": ready, "in_production": in_prod, "not_planned": max(0.0, to_go - ready - in_prod)})
    else:
        given = frappe.get_all("Project Stock Reservation", filters={"status": "Active", "purchase_project": project,
                                                                     "item_code": ["in", items]},
                               fields=["name", "item_code", "batch_no", "production_project"]) if items else []
        rem = _remaining(given)
        to_orders, to_self = defaultdict(float), defaultdict(float)
        for r in given:
            (to_self if same_project(r.production_project, project) else to_orders)[r.item_code] += flt(rem.get(r.name))
        for ln in lines:
            item = ln["item"]
            holding = own_free[item] + to_orders[item] + to_self[item]
            free_now = holding - to_orders[item]
            in_prod = flt(coming.get(item))
            rows.append({**ln, "item_name": (info.get(item) or {}).get("item_name"), "uom": (info.get(item) or {}).get("stock_uom"),
                         "held": holding, "reserved_by_orders": to_orders[item], "free_now": free_now,
                         "in_production": in_prod, "free_after_plan": free_now + in_prod})

    # ── totals and requests ────────────────────────────────────────────────────
    mine = frappe.get_all("Project Stock Reservation", filters={"status": "Active", "production_project": project},
                          fields=["name", "batch_no"])
    rem_mine = _remaining(mine)               # covers every reservation on those batches, other projects' too
    held_total = sum(flt(rem_mine.get(r.name)) for r in mine)
    requests = []
    for mr in frappe.db.sql("""SELECT DISTINCT mr.name, mr.material_request_type, mr.docstatus, mr.status, mr.transaction_date
            FROM `tabMaterial Request` mr JOIN `tabMaterial Request Item` mri ON mri.parent = mr.name
            WHERE mri.project = %s AND mr.docstatus < 2 AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
            ORDER BY mr.creation DESC LIMIT 20""", project, as_dict=True):
        its = frappe.get_all("Material Request Item", filters={"parent": mr.name, "project": project},
                             fields=["item_code", "qty", "uom"], order_by="idx", limit_page_length=6)
        requests.append({"name": mr.name, "kind": mr.material_request_type, "status": "Draft" if mr.docstatus == 0 else mr.status,
                         "lines": [{"item": i.item_code, "qty": flt(i.qty), "uom": i.uom} for i in its]})

    # ── stages, with what open requests and orders will add ────────────────────
    from pranera_planning.api.reservation import get_purchase_project_stock
    try:
        stages = get_purchase_project_stock(project).get("stages") or []
    except frappe.ValidationError:
        stages = []
    planned = defaultdict(float)
    open_items = list(_open_items(project))
    if open_items:
        come_all, _s = planner.coming(project, open_items)
        groups = {i.name: i.item_group for i in frappe.get_all("Item", filters={"name": ["in", open_items]}, fields=["name", "item_group"])}
        # A stage's Planned is what it will produce: made items only. A bought input of the same
        # item group (greige for a dyeing order) would otherwise be counted as that stage's output too.
        made = set(frappe.get_all("BOM", filters={"item": ["in", open_items], "is_active": 1, "docstatus": 1},
                                  pluck="item"))
        for item, q in come_all.items():
            if item in made:
                planned[stage_label(item, groups.get(item)) or ""] += flt(q)
    seen = set()
    for st in stages:
        label = str(st.get("stage") or "").split(" (")[0]
        st["planned_qty"] = round(planned.get(label, 0.0), 3) if label not in seen else 0.0
        seen.add(label)
    for label, q in planned.items():                     # stages with nothing produced yet
        if label and label not in seen and q > EPS:
            stages.append({"stage": label, "orders": 0, "batches": 0, "input_qty": None, "in_process_qty": 0,
                           "produced_qty": 0, "loss_qty": None, "in_stores_qty": 0, "planned_qty": round(q, 3)})

    programme = programme_status(p, plan, rows) if order_type == MTS and rows else None
    so = frappe.db.get_value("Sales Order", p.sales_order, ["customer", "delivery_date"], as_dict=True) if p.sales_order else None
    return {
        "project": {"name": p.name, "project_name": p.project_name, "project_type": p.project_type, "status": p.status,
                    "order_type": order_type, "customer": p.customer or (so.customer if so else None),
                    "sales_order": p.sales_order, "delivery_date": so.delivery_date if so else plan.get("needed_by"),
                    "family": p.get("stock_family"), "period": p.get("stock_period"), "planned_on": plan.get("saved_on")},
        "rows": rows,
        "totals": {"held": held_total, "drafts": sum(1 for r in requests if r["status"] == "Draft"),
                   "delivered": sum(flt(r.get("delivered")) for r in rows),
                   "not_planned": sum(flt(r.get("not_planned")) for r in rows)},
        "requests": requests,
        "stages": stages,
        "programme": programme,
    }


# ── stock programme: at level, below level, period over ──────────────────────

def programme_status(p, plan, rows):
    """Where a made-to-stock programme stands, worked out by the planner itself on its saved
    lines (so it always agrees with what Plan again would buy):

        state      "at_level" (nothing to buy) or "below" (something to buy)
        to_plan    {item: what a plan would request now}; also set on each row as row["to_plan"]
        period_over, period, closed
    Never fails the Overview: if the plan can't be worked out, state is None."""
    out = {"state": None, "to_plan": {}, "period_over": False, "period": p.get("stock_period"),
           "closed": (p.get("status") or "") in ("Completed", "Cancelled")}
    try:
        out["period_over"] = period_over(p)
    except Exception:
        frappe.log_error(title="Stock programme period check failed")
    lines = [{"item": ln["item"], "qty": flt(ln.get("qty")), "mode": ln.get("mode") or "top_up"}
             for ln in plan.get("lines") or [] if ln.get("item") and flt(ln.get("qty")) > EPS]
    if not lines:
        return out
    try:
        prop = planner.propose({"order_type": MTS, "project": p.name, "lines": lines})[0]
    except Exception:
        frappe.log_error(title="Stock programme status failed")
        return out
    wanted = {ln["item"] for ln in lines}
    to_plan = defaultdict(float)
    for lv in prop.get("levels") or []:
        if lv.get("item") in wanted:
            to_plan[lv["item"]] += flt(lv.get("request"))
    for r in rows:
        r["to_plan"] = round(to_plan.get(r["item"], 0.0), 3)
    out["to_plan"] = {k: round(v, 3) for k, v in to_plan.items()}
    out["state"] = "below" if any(v > EPS for v in to_plan.values()) else "at_level"
    return out


def period_over(p):
    """True once today falls in a later period than the one the programme was made for
    (its creation date's period, by Re-order Settings › One project per)."""
    from frappe.utils import getdate, today
    from pranera_planning.reorder_math import period_of
    if not p.get("stock_period"):
        return False
    s = frappe.get_cached_doc("Re-order Settings")
    mode = s.get("stock_project_period") or "Quarter"
    seasons = [(r.season, r.start_month) for r in (s.get("seasons") or []) if r.season and r.start_month]
    created = frappe.db.get_value("Project", p.name, "creation")
    return period_of(getdate(today()), mode, seasons) != period_of(getdate(created), mode, seasons)


@frappe.whitelist(methods=["POST"])
def close_programme(project):
    """Mark a made-to-stock programme Completed (its period is over). Its stock stays where it
    is and stays free for any order; new plans for its family go to the next period's project."""
    frappe.has_permission("Project", "write", project, throw=True)
    p = project_info(project)
    if order_type_of(p) != MTS:
        frappe.throw(_("Only a made-to-stock programme can be closed here."))
    doc = frappe.get_doc("Project", project)
    doc.status = "Completed"
    doc.save()
    doc.add_comment("Comment", _("Stock programme closed from the planning app by {0}.").format(frappe.session.user))
    return {"status": doc.status}
