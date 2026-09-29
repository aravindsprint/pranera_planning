import json
from collections import defaultdict

import frappe
from frappe.utils import flt

from pranera_planning.reservation import (
    get_batch_operations, get_elsewhere_qty, get_issue_lines, get_produced_batches,
    get_reservation_state, reservations_at, roll_tracked_items, stage_of, stage_rank,
)
from pranera_planning.reservation_math import EPS, location_summary, same_project

PROJECT_TYPES = ("Purchase", "Production")


@frappe.whitelist()
def search_purchase_projects(txt="", project_types=None):
    """Projects the page has something to show for — for its "Project" picker: ones that
    have received batch-tracked stock (a submitted Purchase Receipt line with a batch under
    the project), hold a reservation of someone else's stock, or have produced something
    on a Work Order. A plain
    Project search would offer every project, most of which land on the empty state.

    Matches on the project ID or its project_name.

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
             AND (
               EXISTS (
                 SELECT 1 FROM `tabPurchase Receipt Item` pri
                 JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
                 WHERE pri.project = p.name AND IFNULL(pri.batch_no, '') <> ''
               )
               OR EXISTS (
                 SELECT 1 FROM `tabProject Stock Reservation` psr
                 WHERE psr.production_project = p.name AND psr.status IN ('Active', 'Fulfilled')
               )
               OR EXISTS (
                 SELECT 1 FROM `tabWork Order` wo
                 WHERE wo.project = p.name AND wo.docstatus = 1 AND wo.produced_qty > 0
               )
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

    `reserved_for` lists the Active and Fulfilled reservations *held by* `project` on other
    projects' stock — what a Production project sees — with `reserved_totals`.

    `produced_rows` are batches produced for `project` (its Work Orders / Subcontracting
    Receipts), in the same row shape plus `stage`, `made_by` and `elsewhere` (qty in WIP /
    at the subcontractor); `stages` summarises them per stage, in process order.

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
    reserved_for = _reserved_for(project)
    produced = [b for b in get_produced_batches(project) if _in_group(b, item_group)]
    for b in batches:
        b.made_by = None
    rows = _batch_rows(project, batches, "received_qty")
    produced_rows = _batch_rows(project, produced, "produced_qty")
    return {
        "project": project,
        "reserved_for": reserved_for,
        "reserved_totals": _reserved_totals(reserved_for),
        "rows": rows,
        "totals": _totals(rows),
        "produced_rows": produced_rows,
        "produced_totals": _totals(produced_rows),
        "stages": _stages(produced_rows, reserved_for, rows, project),
    }


def _in_group(b, item_group):
    if not item_group or not b.item_group:
        return not item_group
    root = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
    grp = frappe.db.get_value("Item Group", b.item_group, ["lft", "rgt"], as_dict=True)
    return bool(root and grp and grp.lft >= root.lft and grp.rgt <= root.rgt)


def _batch_rows(project, batches, qty_field):
    """One page row per batch — shared by received (Purchase Receipt) and produced batches."""
    batch_nos = [b.batch_no for b in batches]
    if not batch_nos:
        return []
    lines = get_issue_lines(batch_nos)
    state = get_reservation_state(batch_nos, issue_lines=lines)
    roll_items = roll_tracked_items([b.item_code for b in batches])
    produced = qty_field == "produced_qty"
    elsewhere = get_elsewhere_qty(batch_nos) if produced else {}
    operations = get_batch_operations(batch_nos) if produced else {}

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
            "received_qty": flt(b.get(qty_field)),
            "made_by": b.get("made_by"),
            "stage": stage_of(b.item_code, b.get("item_group"), operations.get(b.batch_no)) if produced else None,
            "stage_rank": stage_rank(b.item_code) if produced else None,
            "operation": operations.get(b.batch_no),
            "elsewhere": elsewhere.get(b.batch_no, {}),
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
    return rows


def _stages(produced_rows, reserved_for, received_rows, project):
    """Per stage, in process order, what went in, what came out, and where the output is now.

    A stage is the operation that made the batches (Knitting, Collar Knitting, Dyeing, ...)
    or, failing that, the item code prefix label. Stages are ordered by process step
    (item code prefix: GKF, DKF, SKF, ...); stages on the same step run side by side —
    Knitting, Collar Knitting and Cuff Knitting all take yarn.

    input      what the previous step's batches issued to this project (first step: yarn
               issued to it — its reservations plus its own purchases). Shown only when a
               step has a single stage, since side-by-side stages share their input.
    produced   output batches made for this project
    difference input - produced: still being processed, or lost (process loss)
    """
    by_stage = defaultdict(list)
    for r in produced_rows:
        by_stage[(r["stage_rank"], r["stage"])].append(r)
    by_step = defaultdict(list)
    for rank, label in by_stage:
        by_step[rank].append(label)

    step_input = sum(x["issued_qty"] for x in reserved_for) + sum(r["used_own_qty"] for r in received_rows)
    out = []
    for rank in sorted(by_step):
        labels = sorted(by_step[rank])
        shared = len(labels) > 1
        step_used_own = 0.0
        for label in labels:
            rs = by_stage[(rank, label)]
            produced = sum(r["received_qty"] for r in rs)
            used_own = sum(r["used_own_qty"] for r in rs)
            step_used_own += used_own
            inp = None if shared or not step_input else round(step_input, 3)
            out.append({
                "stage": label,
                "step": rank,
                "shared_step": shared,
                "batches": len(rs),
                "uom": rs[0]["uom"],
                "input_qty": inp,
                "produced_qty": round(produced, 3),
                "difference_qty": round(inp - produced, 3) if inp else None,
                "in_stores_qty": round(sum(r["available_qty"] for r in rs), 3),
                "in_wip_qty": round(sum(r["elsewhere"].get("In WIP", 0) for r in rs), 3),
                "at_subcontractor_qty": round(sum(r["elsewhere"].get("At subcontractor", 0) for r in rs), 3),
                "used_own_qty": round(used_own, 3),
                "used_other_qty": round(sum(x["qty"] for r in rs for x in r["used_other"]), 3),
            })
        step_input = step_used_own
    return out


def _reserved_for(project):
    """Active and Fulfilled reservations held by `project`, one row each, with how much is
    still in stores at the reserved location to back what remains."""
    res = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": ["in", ["Active", "Fulfilled"]], "production_project": project},
        fields=["name", "status", "purchase_project", "item_code", "item_name", "stock_uom", "batch_no",
                "warehouse", "roll_no", "sales_order", "creation"],
        order_by="creation desc",
    )
    if not res:
        return []
    state = get_reservation_state([r.batch_no for r in res], statuses=("Active", "Fulfilled"))
    out = []
    for r in res:
        st = state.get(r.batch_no) or {"locations": {}, "reservations": []}
        live = next((x for x in st["reservations"] if x["name"] == r.name), None)
        if not live:
            continue
        loc = st["locations"].get(r.warehouse, {"available": 0.0, "rolls": {}})
        on_hand = loc["available"]
        if live["roll_no"] and live["roll_no"] in loc["rolls"]:
            on_hand = max(0.0, loc["rolls"][live["roll_no"]])
        out.append({
            "name": r.name,
            "status": r.status,
            "purchase_project": r.purchase_project,
            "item_code": r.item_code,
            "item_name": r.item_name,
            "uom": r.stock_uom,
            "batch_no": r.batch_no,
            "warehouse": r.warehouse,
            "roll_no": live["roll_no"],
            "sales_order": r.sales_order,
            "production_project": project,
            "reserved_qty": live["reserved_qty"],
            "issued_qty": round(min(live["issued_qty"], live["reserved_qty"]), 3),
            "remaining_qty": round(live["remaining_qty"], 3),
            "in_stores_qty": round(min(live["remaining_qty"], max(0.0, on_hand)), 3),
        })
    out.sort(key=lambda x: x["status"] != "Active")
    return out


def _reserved_totals(rows):
    keys = ("reserved_qty", "issued_qty", "remaining_qty", "in_stores_qty")
    return {k: round(sum(r[k] for r in rows), 3) for k in keys}


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
            entry["rolls_uncertain"] = bool(loc.get("rolls_uncertain"))
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
