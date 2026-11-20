"""Is the raw material ready for a stage? For each in-house (or job-work) T&A activity: its
item's BOM inputs, how much of each it still needs, and what covers it.

    need        (planned qty − already produced) × BOM qty per unit (process loss counted)
    covered by  1. already transferred to the activity's Work Orders (material in WIP)
                2. the project's stock in stores: its own free lots plus stock held for it
                   (shared between the project's activities, earliest planned start first)
    short       the rest — expected from the input's own T&A activity (its planned or actual
                end), or from what the project has on order

Status: Ready (all covered) · Partial (some) · Not ready (none); "late" when the rest is expected
after the activity's planned start.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt, getdate

READY, PARTIAL, NOT_READY = "Ready", "Partial", "Not ready"
EPS = 1e-6


def assess(lines, start):
    """Pure: summarise per-input lines [{"need", "transferred", "in_stores", "expected"}] for an
    activity starting on `start`."""
    need = sum(l["need"] for l in lines)
    have = sum(min(l["need"], l["transferred"] + l["in_stores"]) for l in lines)
    short = [l for l in lines if l["transferred"] + l["in_stores"] < l["need"] - EPS]
    if not lines or need <= EPS or not short:
        status = READY
    elif have > EPS:
        status = PARTIAL
    else:
        status = NOT_READY
    exp = [getdate(l["expected"]) for l in short if l.get("expected")]
    expected = max(exp) if len(exp) == len(short) and exp else None
    late = bool(short) and (expected is None or (start and expected > getdate(start)))
    return {"status": status, "pct": round(have / need * 100) if need > EPS else 100,
            "expected": str(expected) if expected else None, "late": late}


def _transferred(project, items):
    """{(made item, input): qty transferred} on the project's open Work Orders."""
    if not items:
        return {}
    out = defaultdict(float)
    used = "IFNULL(woi.consumed_qty, 0)" if frappe.db.has_column("Work Order Item", "consumed_qty") else "0"
    for item, inp, q in frappe.db.sql(
        f"""SELECT wo.production_item, woi.item_code, SUM(woi.transferred_qty - {used})
           FROM `tabWork Order Item` woi JOIN `tabWork Order` wo ON wo.name = woi.parent AND wo.docstatus = 1
            AND wo.status NOT IN ('Completed', 'Closed', 'Stopped', 'Cancelled')
           WHERE wo.project = %(p)s AND wo.production_item IN %(items)s
           GROUP BY wo.production_item, woi.item_code""", {"p": project, "items": tuple(items)}):
        out[(item, inp)] += max(0.0, flt(q))
    return out


def _in_stores(project, items):
    """{input: qty} the project can use from stores: its own free lots + what is held for it."""
    from pranera_planning.planner import free_lots, held_for, same_project
    out = defaultdict(float)
    if not items:
        return out
    for item, lots in free_lots(list(items)).items():
        out[item] += sum(flt(l["qty"]) for l in lots if same_project(l["project"], project))
    for item, q in held_for(project, list(items)).items():
        out[item] += flt(q)
    return out


def readiness(acts):
    """{activity name: {"status", "pct", "expected", "late", "inputs": [...]}} for stage activities
    [{"name", "project", "item_code", "qty", "done_qty", "planned_start"}]."""
    from pranera_planning.planner import bom_tree, coming
    acts = [a for a in acts if a.get("item_code") and a.get("project")]
    if not acts:
        return {}
    _boms, rows = bom_tree({a["item_code"] for a in acts}, depth=1)
    out = {}
    by_project = defaultdict(list)
    for a in acts:
        by_project[a["project"]].append(a)
    for project, group in by_project.items():
        made = {a["item_code"] for a in group}
        inputs = {code for i in made for code, _q in rows.get(i, [])}
        moved = _transferred(project, made)
        stores = _in_stores(project, inputs)
        on_order = coming(project, inputs)[0] if inputs else {}
        expect = _expected(project, inputs)
        left = dict(stores)                                  # shared, earliest start first
        for a in sorted(group, key=lambda x: str(x.get("planned_start") or "")):
            remaining = max(0.0, flt(a.get("qty")) - flt(a.get("done_qty")))
            lines = []
            for inp, per in rows.get(a["item_code"], []):
                need = remaining * per
                tr = moved.get((a["item_code"], inp), 0.0)
                use = min(left.get(inp, 0.0), max(0.0, need - tr))
                left[inp] = left.get(inp, 0.0) - use
                lines.append({"item": inp, "need": round(need, 3), "transferred": round(tr, 3), "in_stores": round(use, 3),
                              "on_order": round(flt(on_order.get(inp)), 3), "expected": expect.get(inp)})
            res = assess(lines, a.get("planned_start"))
            out[a["name"]] = {**res, "inputs": lines, "no_bom": not rows.get(a["item_code"])}
    return out


def _expected(project, inputs):
    """{input: date} it is expected in stores: the end of the input's own T&A activity."""
    if not inputs:
        return {}
    got = frappe.db.sql("""SELECT a.item_code, MAX(COALESCE(a.actual_end, a.planned_end))
        FROM `tabTime and Action Activity` a JOIN `tabTime and Action Plan` p ON p.name = a.parent
        WHERE p.project = %s AND a.item_code IN %s AND a.kind IN ('Stage', 'Bought')
        GROUP BY a.item_code""", (project, tuple(inputs)))
    return {i: str(d) for i, d in got if d}
