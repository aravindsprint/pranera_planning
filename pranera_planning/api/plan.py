"""API for the Plan page. The work is in planner.py."""
import json

import frappe
from frappe import _
from frappe.utils import flt

from pranera_planning import planner

PLANNERS = ("System Manager", "Stock Manager", "Manufacturing Manager", "Purchase Manager")


@frappe.whitelist()
def search_plan_projects(txt=""):
    """Open Production or Purchase projects for a made-to-order plan, newest first."""
    frappe.has_permission("Project", "read", throw=True)
    like = f"%{(txt or '').strip()}%"
    rows = frappe.db.sql(
        """SELECT name, project_name, project_type FROM `tabProject`
           WHERE status = 'Open' AND project_type IN ('Production', 'Purchase')
             AND (name LIKE %(l)s OR IFNULL(project_name, '') LIKE %(l)s)
           ORDER BY modified DESC LIMIT 15""", {"l": like}, as_dict=True)
    return [{"name": r.name, "title": f"{r.project_name or ''} · {r.project_type}".strip(" ·")} for r in rows]


@frappe.whitelist()
def sales_order_lines(sales_order):
    """A Sales Order's customer, delivery date and what is still to deliver per line (stock units)."""
    frappe.has_permission("Sales Order", "read", sales_order, throw=True)
    so = frappe.db.get_value("Sales Order", sales_order, ["name", "customer", "delivery_date", "docstatus", "project"], as_dict=True)
    if not so:
        frappe.throw(_("Sales Order {0} not found.").format(sales_order))
    lines = []
    for r in frappe.get_all("Sales Order Item", filters={"parent": sales_order},
                            fields=["item_code", "item_name", "qty", "delivered_qty", "conversion_factor", "stock_uom", "idx"],
                            order_by="idx"):
        pending = max(0.0, flt(r.qty) - flt(r.delivered_qty)) * (flt(r.conversion_factor) or 1)
        if pending > 1e-9:
            lines.append({"item": r.item_code, "item_name": r.item_name, "qty": round(pending, 3), "uom": r.stock_uom,
                          "label": _("Sales Order line {0}").format(r.idx)})
    return {"sales_order": so.name, "customer": so.customer, "delivery_date": so.delivery_date, "submitted": so.docstatus == 1,
            "project": so.project, "lines": lines}


@frappe.whitelist(methods=["POST"])
def preview(payload):
    frappe.only_for(PLANNERS)
    return planner.propose(json.loads(payload) if isinstance(payload, str) else payload)


@frappe.whitelist(methods=["POST"])
def create_plan(payload):
    """Re-check stock and create everything; all or nothing."""
    frappe.only_for(PLANNERS)
    return planner.create(json.loads(payload) if isinstance(payload, str) else payload)


@frappe.whitelist()
def plan_defaults(project):
    """Where the Plan tab starts for a project: made to order → its Sales Order's open lines
    (else its saved plan); made to stock → its saved targets."""
    frappe.has_permission("Project", "read", project, throw=True)
    from pranera_planning.api.project_planning import order_type_of, project_info, saved_plan
    p = project_info(project)
    order_type = order_type_of(p)
    plan = saved_plan(p)
    out = {"order_type": order_type, "sales_order": None, "sales_order_info": None,
           "needed_by": plan.get("needed_by"), "lines": []}
    if order_type == planner.MTO and p.sales_order:
        so = sales_order_lines(p.sales_order)
        out.update(sales_order=p.sales_order, sales_order_info=so, needed_by=so.get("delivery_date") or out["needed_by"],
                   lines=[{**ln, "mode": "need"} for ln in so["lines"]])
    else:
        default_mode = "need" if order_type == planner.MTO else "top_up"
        out["lines"] = [{"item": ln["item"], "qty": flt(ln["qty"]), "mode": ln.get("mode") or default_mode,
                         "label": _("saved plan")} for ln in plan.get("lines", [])]
    return out
