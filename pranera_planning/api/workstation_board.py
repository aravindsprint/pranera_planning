"""API for the planning app's Workstation Board: machines × days with their load, the in-house
activities waiting for a machine, and booking an activity on a machine.

Booking is blocked (Re-order Settings' choice for T&A restrictions) when the machine doesn't
fit the item (stage, dia, gauge) or would go over its capacity on any day, unless the user has an
override role (Stock Reservation Settings, as for the other checks) and gives a reason, which is
kept in the activity's remarks and as a comment on the T&A plan."""
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from pranera_planning import workstation as W
from pranera_planning import ws_math

ACT, PLAN = W.ACT, W.PLAN


def _stages():
    s = frappe.get_cached_doc("Re-order Settings")
    return [r.stage for r in (s.get("stage_leads") or []) if r.stage]


@frappe.whitelist()
def get_board(stage=None, start=None, days=28):
    frappe.has_permission(PLAN, "read", throw=True)
    stages = _stages()
    stage = stage or (stages[0] if stages else None)
    frm = getdate(start or today())
    days = max(7, min(int(days or 28), 92))
    to = frm + timedelta(days=days)
    wss = W.workstations(stage, frm=frm, to=to)
    books = W.bookings(frm, to, list(wss)) if wss else []
    load = ws_math.load(books, wss, frm, to)
    dates = [frm + timedelta(days=i) for i in range(days)]
    machines = []
    for name, ws in wss.items():
        cells = []
        for d in dates:
            cap = ws_math.capacity_on(ws, d)
            q = load.get((name, d), 0.0)
            cells.append({"date": str(d), "booked": round(q, 1), "capacity": round(cap, 1),
                          "pct": round(q / cap * 100) if cap > 0 else (None if q <= 0 else 999)})
        machines.append({**{k: v for k, v in ws.items() if k != "holidays"},
                         "missing": [x for x, ok in (("Output per hour", ws["kg_per_hour"] > 0), ("Working hours", ws["hours_set"])) if not ok],
                         "cells": cells, "bookings": [_row(b) for b in books if b.workstation == name]})
    wait = W.waiting(stage)
    _add_material(machines, wait)
    fit = W.item_fit({a["item_code"] for a in wait})
    for a in wait:
        a.update(fit.get(a["item_code"]) or {})
        a["candidates"] = _candidates(a, wss)
    return {"stages": stages, "stage": stage, "start": str(frm), "days": days, "dates": [str(d) for d in dates],
            "machines": machines, "waiting": wait, "can_override": _can_override()}


def _row(b):
    return {"activity": b.name, "project": b.project, "item_code": b.item_code, "qty": flt(b.qty), "uom": b.uom,
            "planned_start": str(b.planned_start), "planned_end": str(b.planned_end), "remarks": b.remarks}


def _candidates(a, wss):
    """For a waiting activity: each machine, whether it fits, and its earliest free slot."""
    out = []
    want = {"stage": a.get("stage"), "dia": a.get("dia"), "gauge": a.get("gauge"), "uom": a.get("uom")}
    not_before = max(getdate(a["planned_start"]), getdate(today()))
    for name, ws in wss.items():
        why = ws_math.fits(want, ws)
        slot = None
        if not why and ws["kg_per_hour"] > 0:
            booked = W.booked_by_day(name, ws, not_before, not_before + timedelta(days=150))
            got = ws_math.earliest_slot(ws, booked, ws_math.equivalent(ws, a["qty"], a.get("ops")), not_before)
            slot = {"start": str(got[0]), "end": str(got[1])} if got else None
        out.append({"workstation": name, "fits": not why, "why": why, "slot": slot,
                    "late": bool(slot and getdate(slot["end"]) > getdate(a["planned_end"]))})
    out.sort(key=lambda c: (not c["fits"], c["slot"] is None, c["slot"]["start"] if c["slot"] else ""))
    return out


def _can_override():
    from pranera_planning.reservation import mr_check_settings
    return bool(mr_check_settings()["roles"] & set(frappe.get_roles()))


@frappe.whitelist(methods=["POST"])
def allocate(activity, workstation, start=None, override_reason=None):
    """Book a T&A activity on a workstation from `start` (default: its planned start). The end
    follows from the machine's capacity. Blocked when the machine doesn't fit or would go over
    capacity, unless overridden with a reason by an allowed role."""
    row = frappe.get_doc(ACT, activity)
    plan = frappe.get_doc(PLAN, row.parent)
    frappe.has_permission(PLAN, "write", plan, throw=True)
    if row.kind != "Stage":
        frappe.throw(_("Only a production stage can be booked on a workstation."))
    ws = W.workstations(names=[workstation]).get(workstation)
    if not ws:
        frappe.throw(_("Workstation {0} not found or disabled.").format(workstation))
    start = getdate(start or row.planned_start or today())
    ops = W.item_operations([row.item_code]).get(row.item_code, [])
    qty = ws_math.equivalent(ws, row.qty, ops)              # in the machine's base output
    got = ws_math.duration_for(ws, qty, start)
    if not got:
        frappe.throw(_("{0} has no Output per hour set, so its capacity is unknown: set it on the Workstation.").format(workstation))
    end, n_days = got
    item = {"stage": row.stage, **(W.item_fit([row.item_code]).get(row.item_code) or {})}
    problems = [_("{0} can't make {1}: {2}.").format(workstation, row.item_code, ", ".join(ws_math.fits(item, ws)))] \
        if ws_math.fits(item, ws) else []
    booked = W.booked_by_day(workstation, ws, start, end + timedelta(days=1), exclude=row.name)
    over = ws_math.over_days(ws, booked, qty, start, end)
    if over:
        d, tot, cap = over[0]
        if ws.get("rates"):                                # mixed operations: say it as a share of the day
            problems.append(_("{0} would be over capacity on {1} day(s), first {2}: {3}% of the day booked.")
                            .format(workstation, len(over), frappe.utils.formatdate(d), round(tot / cap * 100) if cap else 999))
        else:
            unit = ws.get("uom") or row.uom or "kg"
            problems.append(_("{0} would be over capacity on {1} day(s), first {2}: {3} {5} booked against {4} {5} a day.")
                            .format(workstation, len(over), frappe.utils.formatdate(d), tot, cap, unit))
    reason = (override_reason or "").strip()
    if problems:
        if not (_can_override() and reason):
            frappe.throw("<br>".join(problems) + ("<br><br>" + _("To book it anyway, give an override reason.")
                                                  if _can_override() else ""), title=_("Can't book this machine"))
    values = {"workstation": workstation, "planned_start": start, "planned_end": end, "duration_days": (end - start).days}
    if reason and problems:
        values["remarks"] = ((row.remarks or "") + f"\nOverride ({frappe.session.user}): {reason}").strip()
        plan.add_comment("Comment", _("{0} booked on {1} with an override: {2} — {3}").format(
            row.activity, workstation, reason, " ".join(problems)))
    frappe.db.set_value(ACT, row.name, values)              # a child row: written directly
    plan.db_set("modified", frappe.utils.now(), update_modified=False)
    row.update(values)
    try:                                                    # put drafts already made on the machine
        from pranera_planning.ta_checks import sync_drafts
        sync_drafts(plan.project, row.item_code)
    except Exception:
        frappe.log_error(title="Moving draft Work Orders onto the booked machine failed")
    late = row.planned_end and plan.deliver_on and getdate(row.planned_end) > getdate(plan.deliver_on)
    return {"activity": row.name, "start": str(start), "end": str(end), "working_days": n_days, "after_delivery": bool(late)}


@frappe.whitelist(methods=["POST"])
def release(activity):
    """Take an activity off its workstation (its dates stay as planned)."""
    row = frappe.get_doc(ACT, activity)
    frappe.has_permission(PLAN, "write", frappe.get_doc(PLAN, row.parent), throw=True)
    frappe.db.set_value(ACT, row.name, "workstation", None)
    return {"activity": row.name}


def _add_material(machines, wait):
    """Raw material readiness on every booking and waiting activity (material_ready.py)."""
    from pranera_planning import ta
    from pranera_planning.material_ready import readiness
    acts = []
    for m in machines:
        for b in m["bookings"]:
            got = ta.actual_for(b["project"], {"kind": "Stage", "route": "In-house", "item_code": b["item_code"]})
            b["done_qty"] = flt(got.get("done_qty"))
            b["actual_start"] = str(got["start"]) if got.get("start") else None
            b["status"] = _status(b)
            acts.append({"name": b["activity"], "project": b["project"], "item_code": b["item_code"], "qty": b["qty"],
                         "done_qty": b["done_qty"], "planned_start": b["planned_start"]})
    acts += [{"name": a["name"], "project": a["project"], "item_code": a["item_code"], "qty": a["qty"],
              "done_qty": a.get("done_qty"), "planned_start": a["planned_start"]} for a in wait]
    try:
        ready = readiness(acts)
    except Exception:
        frappe.log_error(title="Material readiness failed")
        ready = {}
    for m in machines:
        for b in m["bookings"]:
            b["material"] = ready.get(b["activity"])
    for a in wait:
        a["material"] = ready.get(a["name"])


def _status(b):
    """Done · In progress · Late (planned end passed) · Booked."""
    from pranera_planning.ta_math import DONE_SHARE
    if b["qty"] > 0 and b["done_qty"] >= b["qty"] * DONE_SHARE:
        return "Done"
    if b.get("actual_start"):
        return "Late" if getdate(b["planned_end"]) < getdate(today()) else "In progress"
    return "Late" if getdate(b["planned_start"]) < getdate(today()) else "Booked"
