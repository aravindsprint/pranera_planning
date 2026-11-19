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


# ── long runs: preview and create as background jobs ──────────────────────────
# A deep BOM (finishing → dyeing → knitting → yarn, fabrics with thousands of lots) can take
# longer than the web server's request timeout, which then answers 504 and throws the work
# away. start() queues the work and the page polls job_status(); when no background worker is
# running it falls back to doing the work in the request, as before.
#
# The job's state and result are read from the queue itself (RQ keeps them in redis-queue for
# rq_results_ttl, 10 minutes by default), not from the cache: redis-cache evicts keys under
# memory pressure, which lost running jobs ("This plan run has expired") on erptest.
# "default" queue: every worker takes it, so a plan doesn't wait behind long index rebuilds.
JOB_QUEUE = "default"
JOB_TIMEOUT = 1800
JOB_KINDS = ("preview", "create")
JOB_PREFIX = "pranera-plan-"


def _workers_running():
    try:
        from frappe.utils.background_jobs import get_workers
        return bool(get_workers())
    except Exception:
        return False


def _run(kind, payload):
    return planner.propose(payload) if kind == "preview" else planner.create(payload)


@frappe.whitelist(methods=["POST"])
def start(kind, payload):
    """Start a preview or a create. {"status": "done", "result"} when it ran here, else
    {"status": "queued", "job"} to poll with job_status."""
    frappe.only_for(PLANNERS)
    if kind not in JOB_KINDS:
        frappe.throw(_("Unknown plan step {0}.").format(kind))
    payload = json.loads(payload) if isinstance(payload, str) else payload
    if not _workers_running():
        return {"status": "done", "result": _run(kind, payload)}
    job = frappe.generate_hash(length=16)
    frappe.enqueue("pranera_planning.api.plan.run_job", queue=JOB_QUEUE, timeout=JOB_TIMEOUT,
                   job_id=JOB_PREFIX + job, kind=kind, payload=payload)
    return {"status": "queued", "job": job}


def run_job(kind, payload):
    """Background job behind start(). Returns {"ok": True, "result"} or {"ok": False, "error"}
    — an error is returned, not raised, so the page gets a readable message. A create is all
    or nothing: committed only when every reservation and request was made."""
    try:
        result = _run(kind, payload)
        if kind == "create":
            frappe.db.commit()
        return {"ok": True, "result": result}
    except Exception as e:
        frappe.db.rollback()
        if isinstance(e, frappe.ValidationError):
            return {"ok": False, "error": frappe.utils.strip_html(str(e)) or _("The plan could not be made.")}
        frappe.log_error(title=f"Plan {kind} failed")
        return {"ok": False, "error": _("The plan could not be made: {0}. Details are in the Error Log.").format(type(e).__name__)}


def job_state(job):
    """(status, returned) of an RQ job: status is queued | running | done | failed | gone."""
    from frappe.utils.background_jobs import get_job
    rq_job = get_job(JOB_PREFIX + job)
    if not rq_job:
        return "gone", None, None
    owner = (rq_job.kwargs or {}).get("user")
    status = rq_job.get_status()                          # JobStatus is a str Enum: compare its value
    status = str(getattr(status, "value", status) or "")
    if status in ("queued", "deferred", "scheduled"):
        return "queued", None, owner
    if status == "started":
        return "running", None, owner
    if status == "finished":
        returned = rq_job.return_value() if callable(getattr(rq_job, "return_value", None)) else rq_job.result
        return "done", returned, owner
    return "failed", None, owner                          # failed, stopped, canceled


@frappe.whitelist()
def job_status(job):
    """{"status": "queued" | "running" | "done" | "failed", "result"?, "error"?} of your own job."""
    status, returned, owner = job_state(job)
    if status == "gone":
        frappe.throw(_("This plan run is no longer known (results are kept 10 minutes). Run it again."))
    if owner and owner != frappe.session.user:
        frappe.throw(_("Not your plan run."), frappe.PermissionError)
    if status == "done":
        returned = returned or {}
        if returned.get("ok"):
            return {"status": "done", "result": returned.get("result")}
        return {"status": "failed", "error": returned.get("error") or _("The plan could not be made.")}
    if status == "failed":
        return {"status": "failed", "error": _("The plan run stopped unexpectedly. Details are in the Error Log / RQ Job list.")}
    return {"status": status}


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
