"""Time and Action checks on Work Orders and Job Cards (doc_events), blocking with an override:
the same override roles as the other checks (Stock Reservation Settings) plus a reason in
*T&A override reason*, kept as a comment. Re-order Settings › Workstation check: Block (default),
Warn or Off.

Work Order (validate)
    The machine booked for this item on the project's T&A plan is copied onto the operations
    that have none (all of them when there is one operation, else those named like the stage).
    An operation on a machine of the same stage other than the booked one is refused on submit.
Job Card (validate)
    On a machine other than the one booked: refused.
    Started (a time log) while its Work Order has no material transferred yet — the input isn't
    there — refused, unless the Work Order skips the transfer.
"""
import frappe
from frappe import _
from frappe.utils import flt

ACT, PLAN = "Time and Action Activity", "Time and Action Plan"


def _mode():
    try:
        m = frappe.db.get_single_value("Re-order Settings", "workstation_check")
    except Exception:
        m = None
    return m if m in ("Off", "Warn", "Block") else "Block"


def booked_for(project, item):
    """(workstation, stage) the project's T&A plan booked for the item, or (None, None)."""
    if not project or not item or not frappe.db.has_column(ACT, "workstation"):
        return None, None
    row = frappe.db.sql(f"""SELECT a.workstation, a.stage FROM `tab{ACT}` a JOIN `tab{PLAN}` p ON p.name = a.parent
        WHERE p.project = %s AND a.item_code = %s AND a.kind = 'Stage' AND IFNULL(a.workstation, '') != ''
        ORDER BY a.planned_start DESC LIMIT 1""", (project, item))
    return (row[0][0], row[0][1]) if row else (None, None)


def _stage_of_ws(ws):
    if not ws or not frappe.db.has_column("Workstation", "planning_stage"):
        return None
    return (frappe.db.get_value("Workstation", ws, "planning_stage") or "").strip().lower() or None


def _enforce(doc, problems, title):
    """Block (or warn) with the override rule; record an accepted override."""
    if not problems:
        return
    message = "<br>".join(problems)
    if _mode() == "Warn":
        frappe.msgprint(message, title=title, indicator="orange")
        return
    from pranera_planning.reservation import mr_check_settings
    can = bool(mr_check_settings()["roles"] & set(frappe.get_roles()))
    reason = (doc.get("ta_override_reason") or "").strip()
    if can and reason:
        if not doc.flags.get("ta_override_noted"):
            doc.flags.ta_override_noted = True
            if not doc.is_new():
                doc.add_comment("Comment", _("T&A check overridden by {0}: {1} — {2}").format(
                    frappe.session.user, frappe.utils.escape_html(reason), " ".join(problems)))
        return
    frappe.throw(message + ("<br><br>" + _("To go ahead anyway, fill in <b>T&A override reason</b>.") if can else ""),
                 title=title)


def work_order(doc, method=None):
    if _mode() == "Off" or not doc.get("project") or not doc.get("production_item"):
        return
    try:
        ws, stage = booked_for(doc.project, doc.production_item)
        if not ws:
            return
        ops = list(doc.get("operations") or [])
        stage_l = (stage or "").strip().lower()
        for op in ops:
            named = stage_l and stage_l in (op.get("operation") or "").strip().lower()
            if not op.get("workstation") and (len(ops) == 1 or named):
                op.workstation = ws                        # copy the booking
        if doc.docstatus == 0 and getattr(doc, "_action", None) != "submit":
            return
        wrong = [op for op in ops if op.get("workstation") and op.workstation != ws
                 and (len(ops) == 1 or _stage_of_ws(op.workstation) in (None, stage_l))]
        _enforce(doc, [_("Operation {0} is on {1}, but the T&A plan of {2} booked {3} for {4}.").format(
            op.get("operation") or op.idx, op.workstation, doc.project, ws, doc.production_item) for op in wrong],
            _("Not the booked machine"))
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(title="T&A Work Order check failed")


def job_card(doc, method=None):
    if _mode() == "Off" or not doc.get("work_order"):
        return
    try:
        wo = frappe.db.get_value("Work Order", doc.work_order,
                                 ["project", "production_item", "skip_transfer", "material_transferred_for_manufacturing"],
                                 as_dict=True) or {}
        problems = []
        ws, _stage = booked_for(wo.get("project"), wo.get("production_item"))
        if ws and doc.get("workstation") and doc.workstation != ws:
            problems.append(_("{0} is booked on {1} in the T&A plan of {2}, not {3}.").format(
                wo.get("production_item"), ws, wo.get("project"), doc.workstation))
        started = any(t.get("from_time") for t in (doc.get("time_logs") or []))
        if started and not wo.get("skip_transfer") and flt(wo.get("material_transferred_for_manufacturing")) <= 0:
            problems.append(_("Work Order {0} has no material transferred yet: its input isn't there to start on.")
                            .format(doc.work_order))
        _enforce(doc, problems, _("Can't start this job"))
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(title="T&A Job Card check failed")
