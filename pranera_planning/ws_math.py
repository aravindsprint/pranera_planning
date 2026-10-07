"""Workstations: daily capacity, load from bookings, the earliest slot, machine fit.
No frappe imports, so it can be unit-tested anywhere.

Capacity of a workstation on a day (all from the Workstation doctype):
    kg per hour × working hours that day × production capacity (jobs in parallel)
    0 on a holiday of its Holiday List.
A booking (a T&A activity on a workstation) spreads its quantity evenly over the working days
from its planned start up to, not including, its planned end. A day is over-booked when the
bookings on it add up to more than the capacity.
"""
import math
from datetime import date, datetime, timedelta

EPS = 1e-6


def _d(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def days(start, end):
    """The dates from start up to, not including, end (at least the start day)."""
    s, e = _d(start), _d(end)
    if not s:
        return []
    e = e if e and e > s else s + timedelta(days=1)
    return [s + timedelta(days=i) for i in range((e - s).days)]


def capacity_on(ws, day):
    """kg the workstation can do on `day`. ws = {"kg_per_hour", "hours", "parallel", "holidays"}."""
    if _d(day) in (ws.get("holidays") or set()):
        return 0.0
    return float(ws.get("kg_per_hour") or 0) * float(ws.get("hours") or 0) * max(1, int(ws.get("parallel") or 1))


def load(bookings, ws_by_name, frm, to):
    """{(workstation, date): kg booked} for days in [frm, to). Each booking's qty is spread over
    its working days (days with capacity); a booking with no working day loads its start day."""
    frm, to = _d(frm), _d(to)
    out = {}
    for b in bookings:
        ws = ws_by_name.get(b["workstation"]) or {}
        span = days(b["planned_start"], b["planned_end"])
        work = [d for d in span if capacity_on(ws, d) > EPS] or span[:1]
        if not work:
            continue
        each = float(b.get("qty") or 0) / len(work)
        for d in work:
            if frm <= d < to:
                out[(b["workstation"], d)] = out.get((b["workstation"], d), 0.0) + each
    return out


def duration_for(ws, qty, start):
    """Working days the workstation needs for qty from `start` (holidays skipped): returns
    (end date, working days). None when the workstation has no capacity set."""
    start = _d(start)
    per_day = float(ws.get("kg_per_hour") or 0) * float(ws.get("hours") or 0) * max(1, int(ws.get("parallel") or 1))
    if per_day <= EPS:
        return None
    need = max(1, math.ceil(float(qty or 0) / per_day - EPS))
    d, worked = start, 0
    for _ in range(need + 400):                         # holidays can only add so many days
        if capacity_on(ws, d) > EPS:
            worked += 1
            if worked == need:
                return d + timedelta(days=1), need
        d += timedelta(days=1)
    return d, need


def over_days(ws, booked, extra_qty, start, end):
    """[(date, booked + new, capacity)] for days the new booking would push over capacity.
    booked = {date: kg already on this workstation}."""
    span = days(start, end)
    work = [d for d in span if capacity_on(ws, d) > EPS] or span[:1]
    each = float(extra_qty or 0) / max(1, len(work))
    out = []
    for d in work:
        total = booked.get(d, 0.0) + each
        cap = capacity_on(ws, d)
        if total > cap + EPS:
            out.append((d, round(total, 1), round(cap, 1)))
    return out


def earliest_slot(ws, booked, qty, not_before, horizon=120):
    """(start, end) of the earliest run from `not_before` where the workstation has room for
    qty without going over capacity on any day, or None within the horizon."""
    first = _d(not_before)
    for i in range(horizon):
        start = first + timedelta(days=i)
        if capacity_on(ws, start) <= EPS:
            continue
        got = duration_for(ws, qty, start)
        if not got:
            return None
        end, _n = got
        if not over_days(ws, booked, qty, start, end):
            return start, end
    return None


def fits(item, ws):
    """[reasons] a workstation can't make the item: its stage, and for knitting its dia and
    gauge when both the item and the machine have them. Empty list = fits."""
    why = []
    if item.get("stage") and ws.get("stage") and item["stage"].strip().lower() != ws["stage"].strip().lower():
        why.append(f"it is a {ws['stage']} machine, not {item['stage']}")
    for key, label in (("dia", "dia"), ("gauge", "gauge")):
        a, b = item.get(key), ws.get(key)
        if a and b and abs(float(a) - float(b)) > EPS:
            why.append(f"{label} {b:g} ≠ the item's {float(a):g}")
    return why
