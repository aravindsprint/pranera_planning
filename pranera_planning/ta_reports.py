"""Time and Action reports across projects (api.ta_reports).

dashboard()      every open project's activities with their status today: late, due this week,
                 in progress — counted by stage and by customer, with the list to act on.
utilisation()    per workstation and ISO week: booked kg against capacity kg.
delays()         activities finished (or late) in a period: planned vs actual days per stage,
                 average delay, on-time %, and the remarks given as reasons.
"""
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import flt, getdate, today

from pranera_planning import ta, ta_math, workstation as W, ws_math


def _rows(projects=None):
    """[(plan header, activity with status)] for open projects' T&A plans."""
    f = {}
    if projects:
        f["project"] = ["in", projects]
    plans = frappe.get_all(ta.DOCTYPE, filters=f, fields=["name", "project", "customer", "order_type", "deliver_on"])
    status = dict(frappe.get_all("Project", filters={"name": ["in", [p.project for p in plans]]},
                                 fields=["name", "status"], as_list=True)) if plans else {}
    on = today()
    out = []
    for p in plans:
        if status.get(p.project) in ("Completed", "Cancelled"):
            continue
        for a in frappe.get_all("Time and Action Activity",
                                filters={"parent": p.name, "parenttype": ta.DOCTYPE}, fields=["*"], order_by="idx"):
            r = ta._plain(a)
            st = ta_math.status_of(r, ta.actual_for(p.project, r), on)
            out.append((p, {**r, **st}))
    return out


def dashboard(stage=None, customer=None):
    on = getdate(today())
    week_end = on + timedelta(days=7)
    rows = _rows()
    by_stage, by_customer = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    act = []
    totals = defaultdict(int)
    for p, r in rows:
        name = r.get("stage") or ("Buy" if r["kind"] == ta_math.BOUGHT else r.get("activity"))
        cust = p.customer or ("Stock programme" if p.order_type == "Made to stock" else "—")
        if stage and name != stage or customer and cust != customer:
            continue
        done = r["status"] == ta_math.DONE
        late = not done and (r["delay_days"] > 0 or r["late_start"])
        due = not done and r.get("planned_end") and on <= getdate(r["planned_end"]) <= week_end
        key = "late" if late else "due" if due else "in_progress" if r["status"] == ta_math.IN_PROGRESS \
            else "done" if done else "later"
        totals[key] += 1
        by_stage[name][key] += 1
        by_customer[cust][key] += 1
        if key in ("late", "due", "in_progress"):
            act.append({"project": p.project, "customer": cust, "stage": name, "activity": r["activity"],
                        "item_code": r.get("item_code"), "qty": r.get("qty"), "done_qty": r.get("done_qty"),
                        "uom": r.get("uom"), "by": r.get("workstation") or r.get("supplier") or r.get("route"),
                        "planned_start": r.get("planned_start"), "planned_end": r.get("planned_end"),
                        "status": r["status"], "late": late, "late_start": r["late_start"], "delay_days": r["delay_days"],
                        "remarks": r.get("remarks"), "deliver_on": str(p.deliver_on) if p.deliver_on else None, "bucket": key})
    order = {"late": 0, "due": 1, "in_progress": 2}
    act.sort(key=lambda a: (order[a["bucket"]], -(a["delay_days"] or 0), a["planned_end"] or ""))
    pivot = lambda d: [{"name": k, **{x: v.get(x, 0) for x in ("late", "due", "in_progress", "later", "done")}}
                       for k, v in sorted(d.items(), key=lambda kv: (-kv[1].get("late", 0), kv[0]))]
    return {"today": str(on), "totals": dict(totals), "by_stage": pivot(by_stage), "by_customer": pivot(by_customer),
            "activities": act, "stages": sorted(by_stage), "customers": sorted(by_customer)}


def utilisation(stage=None, start=None, weeks=8):
    frm = getdate(start or today())
    frm = frm - timedelta(days=frm.weekday())                # from Monday
    weeks = max(1, min(int(weeks or 8), 26))
    to = frm + timedelta(days=7 * weeks)
    wss = W.workstations(stage, frm=frm, to=to)
    load = ws_math.load(W.bookings(frm, to, list(wss)) if wss else [], wss, frm, to)
    labels = [frm + timedelta(days=7 * i) for i in range(weeks)]
    out = []
    for name, ws in wss.items():
        cells = []
        for w0 in labels:
            cap = sum(ws_math.capacity_on(ws, w0 + timedelta(days=i)) for i in range(7))
            booked = sum(load.get((name, w0 + timedelta(days=i)), 0.0) for i in range(7))
            cells.append({"week": str(w0), "booked": round(booked, 1), "capacity": round(cap, 1),
                          "pct": round(booked / cap * 100) if cap > 0 else None})
        tb, tc = sum(c["booked"] for c in cells), sum(c["capacity"] for c in cells)
        out.append({"workstation": name, "label": ws["label"], "stage": ws["stage"], "cells": cells,
                    "total_pct": round(tb / tc * 100) if tc > 0 else None})
    return {"weeks": [str(w) for w in labels], "machines": out, "stage": stage}


def delays(frm=None, to=None, stage=None):
    """Activities that finished in [frm, to], plus open ones already late."""
    frm = getdate(frm or (getdate(today()) - timedelta(days=90)))
    to = getdate(to or today())
    per = defaultdict(lambda: {"count": 0, "on_time": 0, "planned_days": 0.0, "actual_days": 0.0, "delay": 0.0, "late_open": 0})
    rows = []
    for p, r in _rows():
        if r["kind"] == ta_math.MILESTONE and not r.get("actual_end"):
            continue
        name = r.get("stage") or ("Buy" if r["kind"] == ta_math.BOUGHT else r.get("activity"))
        if stage and name != stage:
            continue
        done = r["status"] == ta_math.DONE and r.get("actual_end") and frm <= getdate(r["actual_end"]) <= to
        late_open = r["status"] != ta_math.DONE and r["delay_days"] > 0
        if not (done or late_open):
            continue
        s = per[name]
        if done:
            planned = (getdate(r["planned_end"]) - getdate(r["planned_start"])).days if r.get("planned_start") else 0
            actual = (getdate(r["actual_end"]) - getdate(r["actual_start"])).days if r.get("actual_start") else 0
            s["count"] += 1
            s["on_time"] += 1 if r["delay_days"] <= 0 else 0
            s["planned_days"] += planned
            s["actual_days"] += actual
            s["delay"] += r["delay_days"]
        else:
            s["late_open"] += 1
        rows.append({"project": p.project, "customer": p.customer, "stage": name, "item_code": r.get("item_code"),
                     "by": r.get("workstation") or r.get("supplier") or r.get("route"),
                     "planned_start": r.get("planned_start"), "planned_end": r.get("planned_end"),
                     "baseline_end": r.get("baseline_end"), "actual_start": r.get("actual_start"),
                     "actual_end": r.get("actual_end"), "status": r["status"], "delay_days": r["delay_days"],
                     "slip_days": r["slip_days"], "remarks": r.get("remarks")})
    stages = []
    for name, s in sorted(per.items()):
        n = s["count"]
        stages.append({"stage": name, "finished": n, "late_open": s["late_open"],
                       "on_time_pct": round(s["on_time"] / n * 100) if n else None,
                       "avg_planned_days": round(s["planned_days"] / n, 1) if n else None,
                       "avg_actual_days": round(s["actual_days"] / n, 1) if n else None,
                       "avg_delay_days": round(s["delay"] / n, 1) if n else None})
    rows.sort(key=lambda r: -(r["delay_days"] or 0))
    n_all = sum(s["count"] for s in per.values())
    on_all = sum(s["on_time"] for s in per.values())
    return {"from": str(frm), "to": str(to), "stages": stages, "rows": rows,
            "on_time_pct": round(on_all / n_all * 100) if n_all else None, "finished": n_all}
