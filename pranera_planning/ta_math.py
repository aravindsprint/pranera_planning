"""Time and Action (T&A): the schedule of a plan's stages, and how each activity stands.
No frappe imports, so it can be unit-tested anywhere.

A plan's levels (planner._propose_one) become activities, scheduled backwards from the date the
goods are needed:

    the top level (the finished item) ends on the delivery / needed-by date;
    each level below ends when the level above it starts;
    an activity lasts its stage's days for its route (In-house or Job work days in Re-order
    Settings), or for a bought item its supplier's lead days.

Only levels with something still to arrive get an activity — what the plan requests now plus
what the project already has coming: stock already in stores needs no time. A last milestone marks the delivery date itself.
"""
import math
from datetime import date, datetime, timedelta

NOT_STARTED, IN_PROGRESS, DONE = "Not started", "In progress", "Done"
STAGE, BOUGHT, MILESTONE = "Stage", "Bought", "Milestone"
DONE_SHARE = 0.98          # 98 % of the planned quantity in counts as done (losses, rounding)


def _d(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _days(x):
    try:
        return max(1, int(math.ceil(float(x or 0))))
    except (TypeError, ValueError):
        return 1


def schedule(levels, deliver_on, final_label="Ready to deliver"):
    """[activity] from a plan's levels, bottom (yarn) first, then the delivery milestone.

    levels  [{"item", "item_name", "uom", "request", "made", "depth", "stage", "route",
              "stage_days", "lead_days", "supplier", "service"}]
    Each activity: {"seq", "activity", "kind", "stage", "item_code", "item_name", "qty", "uom",
                    "route", "supplier", "duration_days", "planned_start", "planned_end", "source"}"""
    deliver_on = _d(deliver_on)
    # What still has to arrive: new requests plus what this project already has coming (its own
    # open requests and orders) — yarn ordered but not yet received is still an activity.
    def todo(lv):
        # all of the project's own open requests and orders, even beyond what the plan counted
        coming = max(float(lv.get("coming") or 0), float(lv.get("coming_all") or 0))
        return float(lv.get("request") or 0) + coming
    work = [lv for lv in levels if todo(lv) > 0]
    by_depth = {}
    for lv in work:
        by_depth.setdefault(int(lv.get("depth") or 0), []).append(lv)

    acts, end = [], deliver_on
    for depth in sorted(by_depth):
        starts = []
        for lv in by_depth[depth]:
            made = bool(lv.get("made"))
            dur = _days(lv.get("stage_days") if made else lv.get("lead_days"))
            start = end - timedelta(days=dur)
            starts.append(start)
            acts.append({
                "activity": (lv.get("stage") or "Make") if made else "Buy",
                "kind": STAGE if made else BOUGHT,
                "stage": lv.get("stage") if made else "",
                "item_code": lv["item"], "item_name": lv.get("item_name") or lv["item"],
                "qty": round(todo(lv), 3), "uom": lv.get("uom") or "",
                "route": (lv.get("route") or "In-house") if made else "Bought",
                "supplier": lv.get("supplier") or "", "service": lv.get("service") or "",
                "duration_days": dur, "planned_start": str(start), "planned_end": str(end),
                "depth": depth, "source": "plan",
            })
        end = min(starts)

    acts.sort(key=lambda a: (-a["depth"], a["planned_start"], a["item_code"]))
    acts.append({"activity": final_label, "kind": MILESTONE, "stage": "", "item_code": "", "item_name": "",
                 "qty": 0, "uom": "", "route": "", "supplier": "", "service": "", "duration_days": 0,
                 "planned_start": str(deliver_on), "planned_end": str(deliver_on), "depth": -1, "source": "plan"})
    for i, a in enumerate(acts, 1):
        a["seq"] = i
        a.pop("depth", None)
    return acts


def merge(old, new):
    """Rebuild a T&A plan without losing what happened. Activities already started, or booked on
    a workstation, keep their planned dates and machine (only the quantity follows the new
    plan); manual milestones stay; the first
    planned end ever given to an activity stays as its baseline, to show how far it slipped."""
    started = {(a.get("kind"), a.get("item_code")): a for a in old
               if a.get("source") == "plan" and a.get("kind") != MILESTONE and a.get("actual_start")}
    # booked on a workstation: the booking is a commitment, so its dates and machine stay too
    booked = {(a.get("kind"), a.get("item_code")): a for a in old
              if a.get("source") == "plan" and a.get("kind") != MILESTONE and a.get("workstation")
              and not a.get("actual_start")}
    baseline = {(a.get("kind"), a.get("item_code"), a.get("activity")): a.get("baseline_end") or a.get("planned_end")
                for a in old if a.get("source") == "plan"}
    out, matched = [], set()
    for a in new:
        matched.add((a["kind"], a["item_code"]))
        key = (a["kind"], a["item_code"])
        keep = started.get(key) or booked.get(key)
        if keep and a["kind"] != MILESTONE:
            a = {**a, "planned_start": keep.get("planned_start"), "planned_end": keep.get("planned_end"),
                 "duration_days": keep.get("duration_days"), "workstation": keep.get("workstation"),
                 "remarks": keep.get("remarks")}
        a["baseline_end"] = baseline.get((a["kind"], a["item_code"], a["activity"])) or a["planned_end"]
        out.append(a)
    # started activities the new plan no longer needs (received, or covered by stock) stay as history
    out += [a for k, a in started.items() if k not in matched]
    out += [a for a in old if a.get("source") != "plan"]
    out.sort(key=lambda a: (str(a.get("planned_end") or "9999"), a.get("kind") == MILESTONE))
    for i, a in enumerate(out, 1):
        a["seq"] = i
    return out


def status_of(act, actual, today):
    """How one activity stands today.

    actual  {"start", "end", "done_qty"} from the documents (empty for a milestone: its own
            actual_end counts)
    Returns {"status", "actual_start", "actual_end", "done_qty", "delay_days", "late_start", "slip_days"}:
      delay_days  done: finished this many days after the planned end (negative = early);
                  not done: today is this many days past the planned end (0 if not yet)
      late_start  not started although the planned start has passed
      slip_days   planned end now vs the first planned end (the baseline)"""
    today = _d(today)
    p_start, p_end = _d(act.get("planned_start")), _d(act.get("planned_end"))
    if act.get("kind") == MILESTONE:
        a_start = a_end = _d(act.get("actual_end"))
        done_qty = 0.0
        done = bool(a_end)
    else:
        a_start, a_end = _d(actual.get("start")), _d(actual.get("end"))
        done_qty = float(actual.get("done_qty") or 0)
        qty = float(act.get("qty") or 0)
        done = qty > 0 and done_qty >= qty * DONE_SHARE
        if not done:
            a_end = None
    status = DONE if done else IN_PROGRESS if a_start else NOT_STARTED
    if done and a_end and p_end:
        delay = (a_end - p_end).days
    elif p_end and today > p_end:
        delay = (today - p_end).days
    else:
        delay = 0
    base = _d(act.get("baseline_end"))
    return {"status": status, "actual_start": str(a_start) if a_start else None,
            "actual_end": str(a_end) if a_end else None, "done_qty": round(done_qty, 3),
            "delay_days": delay, "late_start": bool(status == NOT_STARTED and p_start and today > p_start),
            "slip_days": (p_end - base).days if (base and p_end) else 0}


def summary(rows, today):
    """Counts for the plan header: done, in progress, late, the last planned end."""
    today = _d(today)
    late = [r for r in rows if r["status"] != DONE and (r["delay_days"] > 0 or r["late_start"])]
    ends = [_d(r.get("planned_end")) for r in rows if r.get("planned_end")]
    return {"activities": len(rows), "done": sum(1 for r in rows if r["status"] == DONE),
            "in_progress": sum(1 for r in rows if r["status"] == IN_PROGRESS), "late": len(late),
            "finish": str(max(ends)) if ends else None,
            "on_track": not late}
