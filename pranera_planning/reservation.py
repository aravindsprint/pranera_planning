"""Project stock reservation: the rule that stock reserved for one production project
cannot be used by another, and the Stock Entry hook that enforces it.

Covers any batch-tracked item — yarn, greige/dyed/finished fabric, chemicals, or
finished goods. Nothing here is item-type-specific; scoping which items a particular
page shows is the API layer's job (see api/reservation.py), not this module's.

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
remaining   reserved_qty minus everything issued to that project from that batch since
            the reservation was created.
free        available minus the sum of remaining over all active reservations.

An issue of qty q to project P is allowed when  q <= free + remaining reserved for P.
Batches with no active reservation are never touched by this module.

Site config (all optional)
--------------------------
project_stock_reservation_enforcement                  0 switches enforcement off (default 1)
project_stock_reservation_excluded_warehouse_prefixes  list, default ["WIP", "SUB", "Direct Delivery"]
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from pranera_planning.reservation_math import (
    EPS, allowed_issue_qty, remaining_qty, same_project,
)

ENFORCED_TYPES = ("Material Transfer for Manufacture", "Send to Subcontractor", "Manufacture")
DEFAULT_EXCLUDED_PREFIXES = ("WIP", "SUB", "Direct Delivery")

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


def get_issue_lines(batch_nos):
    """Every submitted issue of these batches: [{batch_no, project, qty, creation}].

    Read from Serial and Batch Entry (batch_no is indexed there; it is not on Stock Entry
    Detail, which made this query scan the whole table). Only outward entries count, so
    finished-goods and target-warehouse lines are excluded automatically.
    """
    if not batch_nos:
        return []
    clause, values = _pool_clause("sbe.warehouse")
    values.update(batches=tuple(batch_nos), types=ENFORCED_TYPES)
    return frappe.db.sql(
        f"""SELECT sbe.batch_no, {PROJECT_EXPR} AS project,
                   ABS(sbe.qty) AS qty, se.creation AS creation
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            JOIN `tabStock Entry` se ON se.name = sbb.voucher_no
            LEFT JOIN `tabWork Order` wo ON wo.name = se.work_order
            WHERE sbe.batch_no IN %(batches)s AND sbe.qty < 0
              AND sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbb.voucher_type = 'Stock Entry'
              AND se.docstatus = 1 AND se.stock_entry_type IN %(types)s
              AND {clause}""",
        values, as_dict=True,
    )


def get_reservation_state(batch_nos, exclude=None, issue_lines=None):
    """{batch: {"available": float, "reservations": [...]}} for the given batches.

    Each reservation carries issued_qty (since it was created) and remaining_qty.
    `exclude` is a reservation name to leave out (used when validating that reservation).
    """
    batch_nos = list(dict.fromkeys(b for b in batch_nos if b))
    if not batch_nos:
        return {}
    available = get_available_qty(batch_nos)
    reservations = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Active", "batch_no": ["in", batch_nos]},
        fields=["name", "batch_no", "production_project", "reserved_qty", "creation"],
    )
    lines = issue_lines if issue_lines is not None else get_issue_lines(batch_nos)

    state = {b: {"available": available.get(b, 0.0), "reservations": []} for b in batch_nos}
    for r in reservations:
        if exclude and r.name == exclude:
            continue
        issued = sum(
            flt(l.qty) for l in lines
            if l.batch_no == r.batch_no
            and same_project(l.project, r.production_project)
            and l.creation >= r.creation
        )
        state[r.batch_no]["reservations"].append({
            "name": r.name,
            "production_project": r.production_project,
            "reserved_qty": flt(r.reserved_qty),
            "issued_qty": issued,
            "remaining_qty": remaining_qty(r.reserved_qty, issued),
        })
    return state


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
    requested = defaultdict(float)
    for row in doc.items:
        if row.batch_no and row.s_warehouse and not row.is_finished_item and is_pool_warehouse(row.s_warehouse):
            requested[row.batch_no] += flt(row.transfer_qty or row.qty)
    if not requested:
        return

    # Fast path: the vast majority of batches have no reservation, and cost one query.
    reserved_batches = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Active", "batch_no": ["in", list(requested)]},
        pluck="batch_no",
    )
    if not reserved_batches:
        return

    project = resolve_project(doc)
    if not project:
        return

    state = get_reservation_state(set(reserved_batches))
    problems = []
    for batch, qty in requested.items():
        st = state.get(batch)
        if not st or not st["reservations"]:
            continue
        allowed, free, own, total = allowed_issue_qty(st["available"], st["reservations"], project)
        if qty > allowed + EPS:
            others = ", ".join(
                f"{r['production_project']}: {r['remaining_qty']:g}"
                for r in st["reservations"]
                if r["remaining_qty"] > EPS and not same_project(r["production_project"], project)
            ) or "-"
            problems.append(_(
                "<b>{0}</b>: issuing {1:g} to project {2}, but only {3:g} can go to it "
                "(unreserved {4:g} + reserved for {2} {5:g}). Reserved for other projects: {6}."
            ).format(batch, qty, project, allowed, free, own, others))

    if problems:
        frappe.throw(
            "<br>".join(problems),
            title=_("This stock is reserved for another project"),
        )
