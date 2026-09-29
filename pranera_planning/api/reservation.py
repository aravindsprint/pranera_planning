import json
from collections import defaultdict

import frappe
from frappe.utils import flt

from pranera_planning.reservation import (
    get_issue_lines, get_reservation_state, reservations_at, roll_tracked_items,
)
from pranera_planning.reservation_math import EPS, location_summary, same_project

PROJECT_TYPES = ("Purchase", "Production")


@frappe.whitelist()
def search_purchase_projects(txt="", project_types=None):
    """Projects that have actually received batch-tracked stock — for the page's "Project"
    picker. A plain Project search would offer every project in the system, including ones
    that never received anything and would just land on the empty state.

    Matches on the project ID or its project_name, scoped to `EXISTS (a submitted Purchase
    Receipt line, with a batch, under this project)`.

    `project_types` is the page's Purchase / Production checkboxes (a list, or its JSON).
    Empty — nothing ticked, or both ticked — means no type filter at all, unclassified
    (blank) projects included; otherwise only projects typed exactly that way.

    Returns `{name, title}` rows — the shape LinkField's `search-fn` prop expects.
    """
    frappe.has_permission("Project Stock Reservation", "read", throw=True)
    if isinstance(project_types, str):
        project_types = json.loads(project_types or "[]")
    types = [t for t in (project_types or []) if t in PROJECT_TYPES]
    type_filter = ""
    params = {"like": f"%{(txt or '').strip()}%"}
    if types and set(types) != set(PROJECT_TYPES):
        type_filter = "AND p.project_type IN %(types)s"
        params["types"] = tuple(types)

    rows = frappe.db.sql(
        f"""SELECT DISTINCT p.name, p.project_name, p.modified
           FROM `tabProject` p
           WHERE (p.name LIKE %(like)s OR IFNULL(p.project_name, '') LIKE %(like)s)
             {type_filter}
             AND EXISTS (
               SELECT 1 FROM `tabPurchase Receipt Item` pri
               JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
               WHERE pri.project = p.name AND IFNULL(pri.batch_no, '') <> ''
             )
           ORDER BY p.modified DESC
           LIMIT 15""",
        params, as_dict=True,
    )
    return [{"name": r.name, "title": r.project_name} for r in rows]


@frappe.whitelist()
def get_purchase_project_stock(project, item_group=None):
    """Everything the Reservation page needs for one purchase project.

    One row per batch bought under `project`, with what was received, what is still
    issuable, what has been issued to which projects (reserved or not), and the active
    reservations with their remaining balance.

    Each row also carries `locations`: one entry per stores warehouse holding the batch,
    with what's reserved and free there. For roll items (fabric, collar, cuff —
    `roll_tracked`), each location lists its numbered rolls and an "unnumbered" remainder,
    since rolls are reserved individually.

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
    roll_items = roll_tracked_items([b.item_code for b in batches])

    issued_by = defaultdict(lambda: defaultdict(float))     # batch -> project -> qty
    for l in lines:
        issued_by[l.batch_no][l.project or "(no project)"] += flt(l.qty)

    rows = []
    for b in batches:
        st = state[b.batch_no]
        reserved_remaining = sum(r["remaining_qty"] for r in st["reservations"])
        used = issued_by[b.batch_no]
        used_own = sum(q for p, q in used.items() if same_project(p, project))
        locations = _locations(st, b.item_code in roll_items)
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
            "free_qty": round(sum(l["free_qty"] for l in locations), 3),
            "roll_tracked": b.item_code in roll_items,
            "locations": locations,
            "reservations": st["reservations"],
        })
    return {"project": project, "rows": rows, "totals": _totals(rows)}


def _locations(st, roll_tracked):
    """Per-warehouse stock for one batch, from get_reservation_state()'s entry."""
    warehouses = set(st["locations"]) | {r["warehouse"] for r in st["reservations"] if r["warehouse"]}
    out = []
    for wh in sorted(warehouses):
        loc = st["locations"].get(wh, {"available": 0.0, "rolls": {}})
        res = reservations_at(st, wh)
        if loc["available"] <= EPS and not res:
            continue
        s = location_summary(loc["available"], loc["rolls"] if roll_tracked else {}, res)
        entry = {
            "warehouse": wh,
            "available_qty": round(loc["available"], 3),
            "reserved_remaining": round(s["reserved"], 3),
            "free_qty": round(s["free"], 3),
        }
        if roll_tracked:
            entry["rolls"] = [
                {"roll_no": roll, "qty": round(v["qty"], 3), "reserved_remaining": round(v["reserved"], 3),
                 "free_qty": round(v["free"], 3)}
                for roll, v in s["rolls"].items()
            ]
            u = s["unnumbered"]
            entry["unnumbered"] = {"qty": round(u["qty"], 3), "reserved_remaining": round(u["reserved"], 3),
                                   "free_qty": round(u["free"], 3)}
        out.append(entry)
    return out


def _totals(rows):
    keys = ("received_qty", "available_qty", "used_own_qty", "reserved_remaining", "free_qty")
    out = {k: round(sum(r[k] for r in rows), 3) for k in keys}
    out["used_other_qty"] = round(sum(o["qty"] for r in rows for o in r["used_other"]), 3)
    return out
