"""Workstations for Time and Action: capacity read from the Workstation doctype, bookings
(T&A activities with a workstation), and in-house activities still waiting for one.
Arithmetic in ws_math.py.

From the Workstation:   Working Hours (hours a day), Production Capacity (jobs in parallel),
                        Holiday List, and the custom fields Planning stage, Kg per hour,
                        Dia and Gauge (patches/add_workstation_fields.py).
From the Item:          Knitting dia and gauge (custom fields), checked against the machine's.
"""
from datetime import timedelta

import frappe
from frappe.utils import flt, getdate

from pranera_planning import ws_math

ACT = "Time and Action Activity"
PLAN = "Time and Action Plan"
DEFAULT_HOURS = 24.0          # a machine with no Working Hours set runs round the clock


def _has(doctype, field):
    try:
        return bool(frappe.db.has_column(doctype, field))
    except Exception:
        return False


def _hours(rows):
    total = 0.0
    for r in rows:
        if r.get("enabled") is not None and not int(r.get("enabled") or 0):
            continue
        s, e = r.get("start_time"), r.get("end_time")
        if s is None or e is None:
            continue
        s = s.total_seconds() if isinstance(s, timedelta) else _secs(s)
        e = e.total_seconds() if isinstance(e, timedelta) else _secs(e)
        total += ((e - s) if e > s else (e + 86400 - s)) / 3600.0
    return total


def _secs(t):
    h, m, *rest = (str(t).split(":") + ["0", "0"])[:3]
    return int(h) * 3600 + int(m) * 60 + int(float(rest[0] or 0))


def workstations(stage=None, names=None, frm=None, to=None):
    """{name: {name, stage, kg_per_hour, hours, hours_set, parallel, dia, gauge, holidays}}."""
    custom = [f for f in ("planning_stage", "kg_per_hour", "machine_dia", "machine_gauge") if _has("Workstation", f)]
    std = [f for f in ("production_capacity", "holiday_list", "disabled") if _has("Workstation", f)]
    filters = {}
    if names:
        filters["name"] = ["in", list(names)]
    rows = frappe.get_all("Workstation", filters=filters, fields=["name", "workstation_name"] + std + custom, order_by="name")
    if stage:
        rows = [r for r in rows if (r.get("planning_stage") or "").strip().lower() == stage.strip().lower()]
    rows = [r for r in rows if not r.get("disabled")]
    if not rows:
        return {}
    hour_fields = ["parent", "start_time", "end_time"] + (["enabled"] if _has("Workstation Working Hour", "enabled") else [])
    hours = {}
    for h in frappe.get_all("Workstation Working Hour", filters={"parent": ["in", [r.name for r in rows]]}, fields=hour_fields):
        hours.setdefault(h.parent, []).append(h)
    hol = {}
    lists = {r.holiday_list for r in rows if r.get("holiday_list")}
    if lists:
        f = {"parent": ["in", list(lists)]}
        if frm and to:
            f["holiday_date"] = ["between", [str(getdate(frm)), str(getdate(to))]]
        for h in frappe.get_all("Holiday", filters=f, fields=["parent", "holiday_date"]):
            hol.setdefault(h.parent, set()).add(getdate(h.holiday_date))
    out = {}
    for r in rows:
        hrs = _hours(hours.get(r.name, []))
        out[r.name] = {"name": r.name, "label": r.get("workstation_name") or r.name, "stage": r.get("planning_stage") or "",
                       "kg_per_hour": flt(r.get("kg_per_hour")), "hours": hrs or DEFAULT_HOURS, "hours_set": bool(hrs),
                       "parallel": int(r.get("production_capacity") or 1), "dia": flt(r.get("machine_dia")) or None,
                       "gauge": flt(r.get("machine_gauge")) or None, "holidays": hol.get(r.get("holiday_list"), set())}
        out[r.name]["per_day"] = ws_math.capacity_on({**out[r.name], "holidays": set()}, getdate())
    return out


def item_fit(items):
    """{item: {"dia", "gauge"}} from the Item's knitting fields."""
    f = [x for x in ("knit_dia", "knit_gauge") if _has("Item", x)]
    if not items or not f:
        return {}
    return {r.name: {"dia": flt(r.get("knit_dia")) or None, "gauge": flt(r.get("knit_gauge")) or None}
            for r in frappe.get_all("Item", filters={"name": ["in", list(items)]}, fields=["name"] + f)}


def _activities(filters, extra=""):
    if not _has(ACT, "workstation"):
        return []
    return frappe.db.sql(f"""SELECT a.name, a.parent, p.project, a.activity, a.stage, a.item_code, a.item_name, a.qty, a.uom,
               a.route, a.workstation, a.planned_start, a.planned_end, a.remarks
        FROM `tab{ACT}` a JOIN `tab{PLAN}` p ON p.name = a.parent
        JOIN `tabProject` pr ON pr.name = p.project AND IFNULL(pr.status, '') NOT IN ('Completed', 'Cancelled')
        WHERE a.parenttype = %(pt)s AND a.kind = 'Stage' {extra}
        ORDER BY a.planned_start""", {"pt": PLAN, **filters}, as_dict=True)


def bookings(frm, to, names=None, exclude=None):
    """Activities booked on workstations that overlap [frm, to)."""
    extra = "AND IFNULL(a.workstation, '') != '' AND a.planned_end > %(frm)s AND a.planned_start < %(to)s"
    if names:
        extra += " AND a.workstation IN %(names)s"
    if exclude:
        extra += " AND a.name != %(exclude)s"
    return _activities({"frm": str(getdate(frm)), "to": str(getdate(to)), "names": tuple(names or ()) or ("",),
                        "exclude": exclude or ""}, extra)


def waiting(stage=None):
    """In-house activities with no workstation yet, not finished, for the stage."""
    from pranera_planning import ta, ta_math
    extra = "AND IFNULL(a.workstation, '') = '' AND IFNULL(a.route, 'In-house') = 'In-house'"
    args = {}
    if stage:
        extra += " AND LOWER(a.stage) = LOWER(%(stage)s)"
        args["stage"] = stage
    out = []
    for a in _activities(args, extra):
        act = {"kind": "Stage", "route": "In-house", "item_code": a.item_code, "qty": a.qty}
        got = ta.actual_for(a.project, act)
        if flt(got.get("done_qty")) >= flt(a.qty) * ta_math.DONE_SHARE:
            continue
        out.append({**a, "done_qty": flt(got.get("done_qty")), "planned_start": str(a.planned_start),
                    "planned_end": str(a.planned_end)})
    return out


def booked_by_day(ws_name, ws, frm, to, exclude=None):
    """{date: kg} already booked on one workstation."""
    load = ws_math.load(bookings(frm, to, [ws_name], exclude), {ws_name: ws}, frm, to)
    return {d: q for (w, d), q in load.items()}
