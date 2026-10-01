"""Re-order arithmetic. No frappe imports, so it can be unit-tested anywhere.

Min–max method, per item, company-wide (made-to-stock output is free for any order, so which
stock project holds it doesn't change these numbers):

    avg / day       = demand in the last N days ÷ N     (sales for finished goods, consumption
                                                          by production for materials)
    safety stock    = avg / day × safety days
    re-order level  = avg / day × lead days + safety stock
    re-order qty    = avg / day × cover days
    max level       = re-order level + re-order qty
    free            = in stores − reserved for orders
    position        = free + WIP (expected output of open orders) + on order
    status          Order now  when position ≤ re-order level
                    Near       when position ≤ re-order level × (1 + near margin)
                    Over max   when position > max level
                    OK         otherwise
    suggest         = max level − position, rounded up to the item's step, when Order now
"""
import math
import re
from datetime import date

EPS = 1e-9


def round_up(qty, step=1.0):
    """Round up to a multiple of step (whole kg, a 25 kg MOQ, …); tiny float noise ignored."""
    step = float(step or 1)
    return math.ceil(round(float(qty) / step, 6)) * step


def reorder_numbers(demand_qty, history_days, lead_days, safety_days, cover_days,
                    in_stores, reserved, wip, on_order, round_to=1.0, near_margin_pct=10.0):
    days = max(1, int(history_days or 1))
    avg = max(0.0, float(demand_qty or 0)) / days
    safety = avg * float(safety_days or 0)
    rol = avg * float(lead_days or 0) + safety
    roq = avg * float(cover_days or 0)
    mx = rol + roq
    free = float(in_stores or 0) - float(reserved or 0)
    position = free + float(wip or 0) + float(on_order or 0)
    if avg <= EPS:
        status = "No demand"
    elif position <= rol + EPS:
        status = "Order now"
    elif position <= rol * (1 + float(near_margin_pct or 0) / 100) + EPS:
        status = "Near"
    elif position > mx + EPS:
        status = "Over max"
    else:
        status = "OK"
    suggest = round_up(mx - position, round_to) if status == "Order now" and mx - position > EPS else 0.0
    return {
        "avg_daily": avg, "safety_qty": safety, "reorder_level": rol, "reorder_qty": roq, "max_level": mx,
        "free": free, "position": position, "status": status, "suggest_qty": suggest,
    }


def stage_days_used(rows, use_learned=False):
    """{stage (lower case): lead days} from the settings' stage rows
    [{"stage", "route", "inhouse_days", "jobwork_days", "override_days"}].

    Days used (override_days) counts. Learned medians count only when use_learned is on and
    Days used is empty — the usual route's figure, else whichever exists. Rounded up to whole
    days; a stage with no days is left out (its items get none, and the report flags them).
    """
    out = {}
    for r in rows:
        stage = str(r.get("stage") or "").strip().lower()
        days = r.get("override_days")
        if not days and use_learned:
            first = r.get("jobwork_days") if (r.get("route") or "") == "Job work" else r.get("inhouse_days")
            days = first or r.get("inhouse_days") or r.get("jobwork_days")
        if stage and days and float(days) > 0:
            out[stage] = math.ceil(round(float(days), 6))
    return out


def median(values):
    xs = sorted(float(v) for v in values if v is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def cumulative_lead(item, stage_days, main_input, bought_days, include_bought=False, _seen=None):
    """Lead days to replenish `item`: its own stage's days plus the stages below it, following
    its main input down the chain.

    stage_days      {item: days of the stage that makes it} — made items only
    main_input      {item: the input it is made from} — its default BOM's main material
    bought_days     {item: supplier lead days} — bought items
    include_bought  False (default): the walk stops at a bought material — it has its own
                    re-order level, which already covers the supplier's lead days, so adding
                    them again would hold the same buffer twice (finished fabric = knitting 5
                    + dyeing 7 + finishing 3 = 15). True adds them (15 + yarn 10 = 25).
    A bought item asked about directly always gets its supplier lead days. A loop in the
    BOM chain stops the walk rather than recursing for ever.
    """
    seen = _seen or set()
    if item in seen:
        return 0.0
    top = not seen
    seen.add(item)
    if item not in stage_days:
        return float(bought_days.get(item) or 0) if (top or include_bought) else 0.0
    below = main_input.get(item)
    rest = cumulative_lead(below, stage_days, main_input, bought_days, include_bought, seen) if below else 0.0
    return float(stage_days[item] or 0) + rest


# ── made-to-stock projects: item family + period ─────────────────────────────

def normalise_family(name):
    """Item family from the Commercial Name: trimmed, upper case, runs of whitespace (tabs
    too) collapsed. Empty or a bare "-" means there is none."""
    s = re.sub(r"\s+", " ", str(name or "")).strip().upper()
    return "" if s in ("", "-") else s


MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def period_of(d, mode, seasons=()):
    """(year, label) of the stock-project period `d` falls in.

    Quarter  → (2026, "Q4");  Month → (2026, "OCT")
    Season   → seasons = [(name, start_month), …]; a date belongs to the season that started
               most recently. A season running over New Year keeps the year it started
               (Winter from August: January 2027 is still Winter 2026).
    """
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    mode = (mode or "Quarter").lower()
    if mode == "month":
        return d.year, MONTHS[d.month - 1]
    if mode == "season" and seasons:
        ordered = sorted(((int(m), n) for n, m in seasons), key=lambda x: x[0])
        started = [(m, n) for m, n in ordered if m <= d.month]
        if started:
            return d.year, started[-1][1].upper()
        return d.year - 1, ordered[-1][1].upper()           # before the first start: last year's last season
    return d.year, f"Q{(d.month - 1) // 3 + 1}"


def stock_project_name(pattern, year, family, period):
    """e.g. "{YY}STK-{FAMILY}-{PERIOD}" → "26STK-2TF ECO 220-Q4"."""
    return (pattern or "{YY}STK-{FAMILY}-{PERIOD}").format(
        YY=f"{year % 100:02d}", YYYY=str(year), FAMILY=family, PERIOD=period)


def deepest(group_bounds, entries):
    """The entry set on the nearest item group above an item (its own group counts).

    group_bounds  (lft, rgt) of the item's group
    entries       [(lft, rgt, payload)] of groups that have something set
    """
    if not group_bounds:
        return None
    lft, rgt = group_bounds
    best = None
    for g_lft, g_rgt, payload in entries:
        if g_lft <= lft and g_rgt >= rgt and (best is None or g_lft > best[0]):
            best = (g_lft, payload)
    return best[1] if best else None


def main_input(bom_items, parent_uom):
    """The material an item is mainly made from, out of its default BOM's rows
    [(item_code, qty, stock_uom, has_batch_no)]: the largest batch-tracked row in the same
    unit as the item (greige into dyed fabric), else simply the largest row."""
    same = [r for r in bom_items if r[3] and r[2] == parent_uom]
    pool = same or list(bom_items)
    return max(pool, key=lambda r: float(r[1] or 0))[0] if pool else None
