"""Project stock reservation: the rule that stock reserved for one production project
cannot be used by another, and the Stock Entry hook that enforces it.

Covers any batch-tracked item. A reservation is held at a stock location:
  yarn and other batch items          warehouse + batch
  fabric, collar, cuff (roll items)   warehouse + batch + roll
Roll items are items under the FABRIC item group tree (collars and cuffs live there too);
see roll_item_groups(). Roll numbers are read from Stock Entry Detail's roll field.

Definitions
-----------
available   qty of a batch sitting in issuable warehouses, i.e. everything except
            WIP / SUB (subcontractor) / Direct Delivery warehouses. Batch.batch_qty is
            NOT used: it counts stock in every warehouse, including WIP.
issue       a Stock Entry source line that takes a batch out of that pool:
            Material Transfer for Manufacture, Manufacture (straight from stores) and
            Send to Subcontractor. Its project is the Work Order's project, or the
            Subcontracting Order item's project. This covers Job Card-triggered
            transfers too — a Job Card doesn't move stock itself, it triggers a Stock
            Entry of one of these same types, which is what this hook actually sees.
remaining   reserved_qty minus everything issued to that project from that batch, out of
            that warehouse (and, for a roll reservation, that roll) since the reservation
            was created.
free        per warehouse: available there minus remaining over its active reservations.

An issue of qty q from warehouse W to project P is allowed when
q <= free at W + remaining reserved for P at W; and a roll reserved for another project
cannot be issued to P at all (beyond any unreserved balance left on that roll).
Batches with no active reservation are never touched by this module.

Site config (all optional)
--------------------------
project_stock_reservation_enforcement                  0 switches enforcement off (default 1)
project_stock_reservation_excluded_warehouse_prefixes  list, default ["WIP", "SUB", "Direct Delivery"]
project_stock_reservation_roll_item_groups             list, default ["FABRIC", "COLLAR", "CUFF"]
                                                       (item group trees reserved by roll; missing
                                                       groups are ignored)
project_stock_reservation_roll_field                   Stock Entry Detail field holding the roll no.,
                                                       default "custom_roll_no"
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from pranera_planning.reservation_math import (
    EPS, allowed_issue_qty, clean_roll, remaining_qty, same_project,
)

ENFORCED_TYPES = ("Material Transfer for Manufacture", "Send to Subcontractor", "Manufacture")
DEFAULT_EXCLUDED_PREFIXES = ("WIP", "SUB", "Direct Delivery")
DEFAULT_ROLL_ITEM_GROUPS = ("FABRIC", "COLLAR", "CUFF")
DEFAULT_ROLL_FIELD = "custom_roll_no"

# Which project does a Stock Entry line belong to?
#  - Send to Subcontractor: the Subcontracting Order item's project, only if unambiguous
#    (the order header project is blank on this site).
#  - everything else: Work Order project, then the entry's own project.
PROJECT_EXPR = """
CASE
  WHEN se.stock_entry_type = 'Send to Subcontractor' THEN (
    SELECT NULLIF(MAX(soi.project), '') FROM `tabSubcontracting Order Item` soi
    WHERE soi.parent = se.subcontracting_order
    HAVING COUNT(DISTINCT soi.project) = 1)
  ELSE COALESCE(NULLIF(wo.project, ''), NULLIF(se.project, ''))
END
"""


# ── configuration ────────────────────────────────────────────────────────────
def is_enabled():
    return bool(int(frappe.conf.get("project_stock_reservation_enforcement", 1)))


def excluded_prefixes():
    return tuple(frappe.conf.get("project_stock_reservation_excluded_warehouse_prefixes") or DEFAULT_EXCLUDED_PREFIXES)


def roll_item_groups():
    return tuple(frappe.conf.get("project_stock_reservation_roll_item_groups") or DEFAULT_ROLL_ITEM_GROUPS)


def roll_field():
    return frappe.conf.get("project_stock_reservation_roll_field") or DEFAULT_ROLL_FIELD


def _roll_expr(alias="sed"):
    """SQL for the roll no. on a Stock Entry Detail row, or NULL on a site without the field."""
    field = roll_field()
    if not frappe.db.has_column("Stock Entry Detail", field):
        return "NULL"
    return f"{alias}.`{field}`"


def roll_tracked_items(item_codes):
    """The subset of item_codes reserved by roll (item group inside a roll_item_groups() tree)."""
    item_codes = list({i for i in item_codes if i})
    if not item_codes:
        return set()
    return set(frappe.db.sql_list(
        """SELECT DISTINCT i.name FROM `tabItem` i
           JOIN `tabItem Group` ig ON ig.name = i.item_group
           JOIN `tabItem Group` root ON root.name IN %(roots)s
           WHERE i.name IN %(items)s AND ig.lft >= root.lft AND ig.rgt <= root.rgt""",
        {"roots": roll_item_groups(), "items": tuple(item_codes)},
    ))


def is_roll_item(item_code):
    return item_code in roll_tracked_items([item_code])


def is_pool_warehouse(warehouse):
    w = (warehouse or "").lower()
    return not any(w.startswith(p.lower()) for p in excluded_prefixes())


def _pool_clause(column):
    """SQL fragment + params keeping only rows whose warehouse is inside the issuable pool."""
    parts, values = [], {}
    for i, prefix in enumerate(excluded_prefixes()):
        key = f"wh_prefix_{i}"
        parts.append(f"{column} NOT LIKE %({key})s")
        values[key] = prefix.replace("%", r"\%").replace("_", r"\_") + "%"
    return " AND ".join(parts) or "1=1", values


# ── queries ──────────────────────────────────────────────────────────────────
def get_batch_purchase_project(batch_no):
    """Project the batch was purchased under (from submitted Purchase Receipt items)."""
    return frappe.db.sql(
        """SELECT MIN(pri.project) FROM `tabPurchase Receipt Item` pri
           JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
           WHERE pri.batch_no = %s AND IFNULL(pri.project, '') <> ''""",
        batch_no,
    )[0][0]


def get_available_qty(batch_nos):
    if not batch_nos:
        return {}
    clause, values = _pool_clause("sbe.warehouse")
    values["batches"] = tuple(batch_nos)
    rows = frappe.db.sql(
        f"""SELECT sbe.batch_no, SUM(sbe.qty) AS qty
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            WHERE sbb.docstatus = 1 AND sbb.is_cancelled = 0
              AND sbe.batch_no IN %(batches)s AND {clause}
            GROUP BY sbe.batch_no""",
        values, as_dict=True,
    )
    out = {b: 0.0 for b in batch_nos}
    out.update({r.batch_no: flt(r.qty) for r in rows})
    return out


def get_stock_locations(batch_nos):
    """{batch: {warehouse: {"available": qty, "rolls": {roll_no: balance}}}} over issuable
    warehouses. Roll balances come from the roll no. on the Stock Entry line behind each
    bundle entry (joined by voucher_detail_no, which is the Stock Entry Detail row name);
    stock moved by any other voucher, or with no roll no., adds to no roll.
    """
    if not batch_nos:
        return {}
    clause, values = _pool_clause("sbe.warehouse")
    values["batches"] = tuple(batch_nos)
    rows = frappe.db.sql(
        f"""SELECT sbe.batch_no, sbe.warehouse, {_roll_expr()} AS roll_no, SUM(sbe.qty) AS qty
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            LEFT JOIN `tabStock Entry Detail` sed
              ON sbb.voucher_type = 'Stock Entry' AND sed.name = sbb.voucher_detail_no
            WHERE sbb.docstatus = 1 AND sbb.is_cancelled = 0
              AND sbe.batch_no IN %(batches)s AND {clause}
            GROUP BY sbe.batch_no, sbe.warehouse, roll_no""",
        values, as_dict=True,
    )
    out = {b: {} for b in batch_nos}
    for r in rows:
        loc = out.setdefault(r.batch_no, {}).setdefault(r.warehouse, {"available": 0.0, "rolls": defaultdict(float)})
        loc["available"] += flt(r.qty)
        roll = clean_roll(r.roll_no)
        if roll:
            loc["rolls"][roll] += flt(r.qty)
    for locs in out.values():
        for loc in locs.values():
            loc["rolls"] = dict(loc["rolls"])
    return out


def get_issue_lines(batch_nos):
    """Every submitted issue of these batches:
    [{batch_no, warehouse, roll_no, project, qty, creation}].

    Read from Serial and Batch Entry (batch_no is indexed there; it is not on Stock Entry
    Detail, which made this query scan the whole table). Only outward entries count, so
    finished-goods and target-warehouse lines are excluded automatically.
    """
    if not batch_nos:
        return []
    clause, values = _pool_clause("sbe.warehouse")
    values.update(batches=tuple(batch_nos), types=ENFORCED_TYPES)
    lines = frappe.db.sql(
        f"""SELECT sbe.batch_no, sbe.warehouse, {_roll_expr()} AS roll_no, {PROJECT_EXPR} AS project,
                   ABS(sbe.qty) AS qty, se.creation AS creation
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            JOIN `tabStock Entry` se ON se.name = sbb.voucher_no
            LEFT JOIN `tabStock Entry Detail` sed ON sed.name = sbb.voucher_detail_no
            LEFT JOIN `tabWork Order` wo ON wo.name = se.work_order
            WHERE sbe.batch_no IN %(batches)s AND sbe.qty < 0
              AND sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbb.voucher_type = 'Stock Entry'
              AND se.docstatus = 1 AND se.stock_entry_type IN %(types)s
              AND {clause}""",
        values, as_dict=True,
    )
    for l in lines:
        l.roll_no = clean_roll(l.roll_no)
    return lines


def get_reservation_state(batch_nos, exclude=None, issue_lines=None):
    """{batch: {"available", "locations", "reservations"}} for the given batches.

    available     total in issuable warehouses
    locations     {warehouse: {"available", "rolls"}}, see get_stock_locations()
    reservations  active ones, each with warehouse, roll_no, issued_qty (issued to its project
                  from that warehouse — and roll, if it has one — since it was created) and
                  remaining_qty.
    `exclude` is a reservation name to leave out (used when validating that reservation).
    """
    batch_nos = list(dict.fromkeys(b for b in batch_nos if b))
    if not batch_nos:
        return {}
    locations = get_stock_locations(batch_nos)
    reservations = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Active", "batch_no": ["in", batch_nos]},
        fields=["name", "batch_no", "warehouse", "roll_no", "production_project", "reserved_qty", "creation"],
    )
    lines = issue_lines if issue_lines is not None else get_issue_lines(batch_nos)

    state = {
        b: {
            "available": sum(l["available"] for l in locations.get(b, {}).values()),
            "locations": locations.get(b, {}),
            "reservations": [],
        }
        for b in batch_nos
    }
    for r in reservations:
        if exclude and r.name == exclude:
            continue
        roll = clean_roll(r.roll_no)
        issued = sum(
            flt(l.qty) for l in lines
            if l.batch_no == r.batch_no
            and l.warehouse == r.warehouse
            and (not roll or l.roll_no == roll)
            and same_project(l.project, r.production_project)
            and l.creation >= r.creation
        )
        state[r.batch_no]["reservations"].append({
            "name": r.name,
            "production_project": r.production_project,
            "warehouse": r.warehouse,
            "roll_no": roll,
            "reserved_qty": flt(r.reserved_qty),
            "issued_qty": issued,
            "remaining_qty": remaining_qty(r.reserved_qty, issued),
        })
    return state


def reservations_at(state, warehouse):
    """The reservations in one batch's state that sit at `warehouse`."""
    return [r for r in state["reservations"] if r["warehouse"] == warehouse]


# ── Stock Entry hook ─────────────────────────────────────────────────────────
def resolve_project(doc):
    if doc.stock_entry_type == "Send to Subcontractor":
        if not doc.get("subcontracting_order"):
            return None
        projects = frappe.db.sql_list(
            """SELECT DISTINCT project FROM `tabSubcontracting Order Item`
               WHERE parent = %s AND IFNULL(project, '') <> ''""",
            doc.subcontracting_order,
        )
        return projects[0] if len(projects) == 1 else None

    project = frappe.db.get_value("Work Order", doc.work_order, "project") if doc.get("work_order") else None
    return project or doc.get("project") or None


def validate_stock_entry(doc, method=None):
    """doc_events hook: Stock Entry.validate.

    Only a deliberate ValidationError stops the entry. Any other failure in this module is
    logged and the entry is let through, so a bug here can never halt the shop floor.
    """
    if not is_enabled() or doc.stock_entry_type not in ENFORCED_TYPES:
        return
    try:
        _check(doc)
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(title="Project stock reservation check failed (entry allowed through)")


def _check(doc):
    field = roll_field()
    requested = defaultdict(float)          # (batch, warehouse) -> qty
    requested_roll = defaultdict(float)     # (batch, warehouse, roll) -> qty
    for row in doc.items:
        if row.batch_no and row.s_warehouse and not row.is_finished_item and is_pool_warehouse(row.s_warehouse):
            qty = flt(row.transfer_qty or row.qty)
            requested[(row.batch_no, row.s_warehouse)] += qty
            roll = clean_roll(row.get(field))
            if roll:
                requested_roll[(row.batch_no, row.s_warehouse, roll)] += qty
    if not requested:
        return

    # Fast path: the vast majority of batches have no reservation, and cost one query.
    reserved_batches = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Active", "batch_no": ["in", list({b for b, _ in requested})]},
        pluck="batch_no",
    )
    if not reserved_batches:
        return

    project = resolve_project(doc)
    if not project:
        return

    state = get_reservation_state(set(reserved_batches))
    problems = []

    for (batch, wh), qty in requested.items():
        st = state.get(batch)
        res = reservations_at(st, wh) if st else []
        if not res:
            continue
        loc = st["locations"].get(wh, {"available": 0.0, "rolls": {}})
        allowed, free, own, total = allowed_issue_qty(loc["available"], res, project)
        if qty > allowed + EPS:
            problems.append(_(
                "<b>{0}</b> in {1}: issuing {2:g} to project {3}, but only {4:g} can go to it "
                "(unreserved {5:g} + reserved for {3} {6:g}). Reserved for other projects: {7}."
            ).format(batch, wh, qty, project, allowed, free, own, _others(res, project)))

    for (batch, wh, roll), qty in requested_roll.items():
        st = state.get(batch)
        res = reservations_at(st, wh) if st else []
        on_roll = [r for r in res if r["roll_no"] == roll]
        if not on_roll:
            continue
        loc = st["locations"].get(wh, {"available": 0.0, "rolls": {}})
        allowed, *_ = allowed_issue_qty(loc["available"], res, project, loc["rolls"], roll)
        if qty > allowed + EPS:
            problems.append(_(
                "<b>{0}</b> roll <b>{1}</b> in {2} is reserved for {3} — it cannot be issued to project {4}."
            ).format(batch, roll, wh, _others(on_roll, project), project))

    if problems:
        frappe.throw(
            "<br>".join(problems),
            title=_("This stock is reserved for another project"),
        )


def _others(reservations, project):
    return ", ".join(
        f"{r['production_project']}: {r['remaining_qty']:g}"
        for r in reservations
        if r["remaining_qty"] > EPS and not same_project(r["production_project"], project)
    ) or "-"
