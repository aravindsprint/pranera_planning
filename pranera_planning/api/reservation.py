from collections import defaultdict

import frappe
from frappe.utils import flt

from pranera_planning.reservation import (
    get_available_qty, get_issue_lines, get_reservation_state,
)
from pranera_planning.reservation_math import same_project


@frappe.whitelist()
def get_purchase_project_stock(project, item_group=None):
    """Everything the Reservation page needs for one purchase project.

    One row per batch bought under `project`, with what was received, what is still
    issuable, what has been issued to which projects (reserved or not), and the active
    reservations with their remaining balance.

    `item_group` is optional and restricts the result to that Item Group's tree (e.g.
    "YARN", "FABRIC") — pass nothing to see every batch-tracked item bought under the
    project, whatever it is.
    """
    frappe.has_permission("Project Stock Reservation", "read", throw=True)

    group_join, group_filter, params = "", "", [project]
    if item_group:
        group_join = """
            JOIN `tabItem Group` ig ON ig.name = i.item_group
            JOIN `tabItem Group` root ON root.name = %s
        """
        group_filter = "AND ig.lft >= root.lft AND ig.rgt <= root.rgt"
        params = [item_group, project]

    batches = frappe.db.sql(
        f"""SELECT pri.item_code, MAX(pri.item_name) AS item_name, pri.stock_uom, pri.batch_no,
                   ROUND(SUM(pri.stock_qty), 3) AS received_qty
            FROM `tabPurchase Receipt Item` pri
            JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
            JOIN `tabItem` i ON i.name = pri.item_code
            {group_join}
            WHERE pri.project = %s AND IFNULL(pri.batch_no, '') <> ''
              {group_filter}
            GROUP BY pri.item_code, pri.stock_uom, pri.batch_no
            ORDER BY pri.item_code, pri.batch_no""",
        params, as_dict=True,
    )
    batch_nos = [b.batch_no for b in batches]
    if not batch_nos:
        return {"project": project, "rows": [], "totals": _totals([])}

    lines = get_issue_lines(batch_nos)
    state = get_reservation_state(batch_nos, issue_lines=lines)

    issued_by = defaultdict(lambda: defaultdict(float))     # batch -> project -> qty
    for l in lines:
        issued_by[l.batch_no][l.project or "(no project)"] += flt(l.qty)

    rows = []
    for b in batches:
        st = state[b.batch_no]
        reserved_remaining = sum(r["remaining_qty"] for r in st["reservations"])
        used = issued_by[b.batch_no]
        used_own = sum(q for p, q in used.items() if same_project(p, project))
        rows.append({
            "item_code": b.item_code,
            "item_name": b.item_name,
            "uom": b.stock_uom,
            "batch_no": b.batch_no,
            "received_qty": flt(b.received_qty),
            "available_qty": st["available"],
            "used_own_qty": used_own,
            "used_other": sorted(
                ({"project": p, "qty": q} for p, q in used.items() if not same_project(p, project)),
                key=lambda x: -x["qty"],
            ),
            "reserved_remaining": reserved_remaining,
            "free_qty": max(0.0, st["available"] - reserved_remaining),
            "reservations": st["reservations"],
        })
    return {"project": project, "rows": rows, "totals": _totals(rows)}


def _totals(rows):
    keys = ("received_qty", "available_qty", "used_own_qty", "reserved_remaining", "free_qty")
    out = {k: round(sum(r[k] for r in rows), 3) for k in keys}
    out["used_other_qty"] = round(sum(o["qty"] for r in rows for o in r["used_other"]), 3)
    return out
