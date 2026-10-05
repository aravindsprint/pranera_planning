"""Plan page: gathers what a project has, is getting, and could borrow; runs the plan
(plan_math.build_plan); turns it into reservations per lot and draft Material Requests; and,
on Create, makes them. Create always rebuilds the proposal first, so it never acts on stale
numbers.

Made to order   one project, chosen by the planner (lines usually from its Sales Order).
Made to stock   each line goes to the stock project of its family and period:
                family = Commercial Name (cleaned up), else the top item group;
                made items → a Production stock project, bought items → a Purchase one;
                named by Re-order Settings' pattern, created on Create if it doesn't exist.

Per item:
  own        made to order: the project's free stock + what is already reserved for it
             made to stock: free stock in ANY made-to-stock project (last period's stock of
                            the same quality is used before making more)
  coming     the project's open Work / Subcontracting / Purchase Orders and Material Requests
             (draft requests too — re-planning never orders twice), as expected output
  borrowable other projects' free stock that was purchased under them — not stock produced
             for them (theirs), not made-to-order projects' stock (their order's)
Roll items are reserved roll by roll; their unnumbered stock can't be reserved, so it isn't offered.
"""
import json
import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from pranera_planning.plan_math import allocate_lots, build_plan, scenario_rules
from pranera_planning.reorder import _top_group, load_settings
from pranera_planning.reorder_math import (
    DEFAULT_STOCK_PATTERN, deepest, next_seq, normalise_family, period_of, stock_project_name,
)
from pranera_planning.reservation import (
    EPS, get_produced_owners, get_reservation_state, get_stock_locations, reservations_at, roll_tracked_items,
    same_project, stage_of,
)
from pranera_planning.reservation_math import location_summary

MTS, MTO = "Made to stock", "Made to order"
DONE = ("Completed", "Closed", "Cancelled", "Stopped")


def _has(doctype, field):
    return frappe.db.has_column(doctype, field)


def company():
    return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")


# ── items and BOMs ────────────────────────────────────────────────────────────

def item_info(codes):
    codes = list({c for c in codes if c})
    if not codes:
        return {}
    fields = ["name", "item_name", "item_group", "stock_uom", "is_stock_item", "has_batch_no", "lead_time_days"]
    if _has("Item", "commercial_name"):
        fields.append("commercial_name")
    return {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", codes]}, fields=fields)}


def bom_tree(codes, depth=10, chosen=None):
    """({item: BOM}, {item: [(input, qty per 1 unit of good output)]}) down from `codes`;
    stock inputs only. `chosen` {item: BOM} overrides the default BOM (an active, submitted
    BOM of that item). A BOM's Process Loss % counts: 1,000 kg at 3% loss needs 1,000 ÷ 0.97
    of input — only part of what goes in comes out good."""
    chosen = {k: v for k, v in (chosen or {}).items() if k and v}
    loss_field = ["process_loss_percentage"] if frappe.db.has_column("BOM", "process_loss_percentage") else []
    boms, rows, todo, seen = {}, {}, set(codes), set()
    for _d in range(depth):
        todo -= seen
        if not todo:
            break
        seen |= todo
        picked = [chosen[i] for i in todo if i in chosen]
        found = {b.item: b for b in frappe.get_all(
            "BOM", filters={"name": ["in", picked], "is_active": 1, "docstatus": 1},
            fields=["name", "item", "quantity"] + loss_field)} if picked else {}
        found = {i: b for i, b in found.items() if chosen.get(i) == b.name}
        rest = [i for i in todo if i not in found]
        if rest:
            for b in frappe.get_all("BOM", filters={"item": ["in", rest], "is_default": 1, "is_active": 1, "docstatus": 1},
                                    fields=["name", "item", "quantity"] + loss_field):
                found.setdefault(b.item, b)
        todo = set()
        if not found:
            continue
        lines = defaultdict(list)
        for parent, code, qty, stock in frappe.db.sql(
            """SELECT bi.parent, bi.item_code, bi.stock_qty, i.is_stock_item FROM `tabBOM Item` bi
               JOIN `tabItem` i ON i.name = bi.item_code WHERE bi.parent IN %(b)s""",
            {"b": tuple(b.name for b in found.values())},
        ):
            if stock:
                lines[parent].append((code, flt(qty)))
        for item, b in found.items():
            boms[item] = b.name
            loss = min(max(flt(b.get("process_loss_percentage")), 0.0), 99.0)
            per = (flt(b.quantity) or 1.0) * (1 - loss / 100)
            rows[item] = [(code, qty / per) for code, qty in lines[b.name]]
            todo |= {code for code, _q in rows[item]}
    return boms, rows


# ── stock: lots, held, coming ─────────────────────────────────────────────────

def free_lots(items):
    """{item: [{"batch_no", "warehouse", "roll_no", "qty", "project", "produced"}]}, oldest batch
    first. Free = in stores minus what active reservations hold there. Roll items list free
    numbered rolls only."""
    items = list(items)
    batches = frappe.get_all("Batch", filters={"item": ["in", items], "batch_qty": [">", EPS], "disabled": 0},
                             fields=["name", "item"], order_by="creation asc") if items else []
    if not batches:
        return {}
    item_of = {b.name: b.item for b in batches}
    names = list(item_of)
    locations = get_stock_locations(names)
    purchased = dict(frappe.db.sql(
        """SELECT pri.batch_no, MAX(pri.project) FROM `tabPurchase Receipt Item` pri
           JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
           WHERE pri.batch_no IN %(b)s AND IFNULL(pri.project, '') <> '' GROUP BY pri.batch_no""", {"b": tuple(names)}))
    owners = get_produced_owners(names)
    reserved = set(frappe.get_all("Project Stock Reservation", filters={"status": "Active", "batch_no": ["in", names]},
                                  pluck="batch_no"))
    state = get_reservation_state(reserved) if reserved else {}
    rolls = roll_tracked_items(set(item_of.values()))

    out = defaultdict(list)
    for batch in names:
        item = item_of[batch]
        project = purchased.get(batch) or owners.get(batch)
        produced = batch not in purchased and batch in owners
        for wh, loc in sorted((locations.get(batch) or {}).items()):
            res = reservations_at(state[batch], wh) if batch in state else []
            summ = location_summary(loc["available"], loc["rolls"] if item in rolls else {}, res)
            base = {"batch_no": batch, "warehouse": wh, "project": project, "produced": produced}
            if item in rolls:
                for roll, v in summ["rolls"].items():
                    if v["free"] > EPS:
                        out[item].append({**base, "roll_no": roll, "qty": v["free"]})
            elif summ["free"] > EPS:
                out[item].append({**base, "roll_no": "", "qty": summ["free"]})
    return out


def held_for(project, items):
    """{item: qty} still reserved for `project` (Active reservations' remaining)."""
    rows = frappe.get_all("Project Stock Reservation", filters={"status": "Active", "production_project": project,
                                                                "item_code": ["in", list(items)]},
                          fields=["name", "item_code", "batch_no"]) if project and items else []
    if not rows:
        return {}
    remaining = {r["name"]: r["remaining_qty"] for st in get_reservation_state({r.batch_no for r in rows}).values()
                 for r in st["reservations"]}
    out = defaultdict(float)
    for r in rows:
        out[r.item_code] += flt(remaining.get(r.name))
    return out


def coming(project, items):
    """({item: qty}, {item: [text]}) the project's open orders will still deliver."""
    qty, src = defaultdict(float), defaultdict(list)
    if not project or not items:
        return qty, src
    v = {"p": project, "items": tuple(items)}

    def add(rows, label):
        for item, q, n in rows:
            if flt(q) > EPS:
                qty[item] += flt(q)
                src[item].append(f"{label} {n}")

    add(frappe.db.sql(f"""SELECT production_item, SUM(GREATEST(qty - produced_qty, 0)), COUNT(*) FROM `tabWork Order`
                          WHERE docstatus = 1 AND status NOT IN {DONE} AND project = %(p)s AND production_item IN %(items)s
                          GROUP BY production_item""", v), "Work Orders:")
    add(frappe.db.sql(f"""SELECT soi.item_code, SUM(GREATEST(soi.qty - soi.received_qty, 0) * IFNULL(NULLIF(soi.conversion_factor, 0), 1)), COUNT(*)
                          FROM `tabSubcontracting Order Item` soi
                          JOIN `tabSubcontracting Order` sco ON sco.name = soi.parent AND sco.docstatus = 1 AND sco.status NOT IN {DONE}
                          LEFT JOIN `tabPurchase Order Item` poi ON poi.name = soi.purchase_order_item
                          WHERE (soi.project = %(p)s OR poi.project = %(p)s) AND soi.item_code IN %(items)s
                          GROUP BY soi.item_code""", v), "Subcontracting Orders:")
    add(frappe.db.sql(f"""SELECT poi.item_code, SUM(GREATEST(poi.qty - poi.received_qty, 0) * IFNULL(NULLIF(poi.conversion_factor, 0), 1)), COUNT(*)
                          FROM `tabPurchase Order Item` poi
                          JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
                           AND po.status NOT IN {DONE + ('Delivered', 'On Hold')} AND IFNULL(po.is_subcontracted, 0) = 0
                          WHERE poi.project = %(p)s AND poi.item_code IN %(items)s GROUP BY poi.item_code""", v), "Purchase Orders:")
    proj = "(mri.project = %(p)s" + (" OR mri.for_project = %(p)s)" if _has("Material Request Item", "for_project") else ")")
    add(frappe.db.sql(f"""SELECT mri.item_code, SUM(GREATEST(mri.stock_qty - mri.ordered_qty, 0)), COUNT(*)
                          FROM `tabMaterial Request Item` mri
                          JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus < 2
                           AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled', 'Ordered', 'Transferred', 'Issued', 'Received')
                           AND mr.material_request_type IN ('Purchase', 'Manufacture')
                          WHERE {proj} AND mri.item_code IN %(items)s GROUP BY mri.item_code""", v), "Material Requests (incl. drafts):")
    return qty, src


def last_service(items):
    """{item: the job-work service its most recent Purchase Material Request bought against
    one of its BOMs} — e.g. which fabrics go to the stenter and which to the dryer."""
    if not items:
        return {}
    out = {}
    for item, svc in frappe.db.sql(
        """SELECT b.item, mri.item_code FROM `tabMaterial Request Item` mri
           JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus = 1 AND mr.material_request_type = 'Purchase'
           JOIN `tabItem` i ON i.name = mri.item_code AND i.is_stock_item = 0
           JOIN `tabBOM` b ON b.name = mri.bom_no
           WHERE b.item IN %(items)s ORDER BY mr.transaction_date DESC, mr.creation DESC""", {"items": tuple(items)}):
        out.setdefault(item, svc)
    return out


# ── made-to-stock projects ────────────────────────────────────────────────────

def stock_project_for(item, made, settings, on):
    """The made-to-stock project a line goes to. With {SEQ} in the pattern every new plan gets
    its own project, numbered per family and period (…-Q4-01, …-Q4-02); without it, one project
    per family and period is reused."""
    family = normalise_family(item.get("commercial_name")) or _top_group(item.item_group) or "STOCK"
    seasons = [(r.season, r.start_month) for r in (settings.get("seasons") or []) if r.season and r.start_month]
    year, label = period_of(on, settings.get("stock_project_period") or "Quarter", seasons)
    pattern = settings.get("stock_project_pattern") or DEFAULT_STOCK_PATTERN
    kind = "Production" if made else "Purchase"
    if "{SEQ}" in pattern:
        before, after = stock_project_name(pattern, year, family, label).split("{SEQ}", 1)
        taken = frappe.get_all("Project", filters={"project_name": ["like", f"{before}%{after}"]}, pluck="project_name")
        name = stock_project_name(pattern, year, family, label, next_seq(pattern, year, family, label, taken))
        return {"project": None, "project_name": name, "family": family, "period": label, "project_type": kind, "exists": False}
    name = stock_project_name(pattern, year, family, label)
    existing = frappe.db.get_value("Project", {"project_name": name}, ["name", "project_type"], as_dict=True)
    return {"project": existing.name if existing else None, "project_name": name, "family": family, "period": label,
            "project_type": kind, "exists": bool(existing)}


# ── the proposal ──────────────────────────────────────────────────────────────

def propose(payload):
    """[proposal per project] for payload {order_type, project?, sales_order?, needed_by?,
    lines: [{item, qty, mode}], routes?: {item: "In-house" | "Job work"}}."""
    payload = json.loads(payload) if isinstance(payload, str) else payload
    order_type = payload.get("order_type") or MTO
    lines = [ln for ln in payload.get("lines") or [] if ln.get("item") and flt(ln.get("qty")) > EPS]
    if not lines:
        frappe.throw(_("Add at least one item and quantity."))
    cfg = load_settings()
    settings = cfg["doc"]
    on = getdate(payload.get("needed_by") or today())

    if order_type == MTO:
        project = payload.get("project")
        if not project:
            frappe.throw(_("Choose the made-to-order project."))
        p = frappe.db.get_value("Project", project, ["name", "project_name", "project_type", "status", "customer"], as_dict=True)
        if not p:
            frappe.throw(_("Project {0} not found.").format(project))
        groups = [({"project": p.name, "project_name": p.project_name, "project_type": p.project_type or "Production",
                    "exists": True, "customer": p.customer}, [{**ln, "mode": ln.get("mode") or "need"} for ln in lines])]
    elif payload.get("project"):
        # Re-planning an existing made-to-stock project (its own Plan tab): keep that project.
        p = frappe.db.get_value("Project", payload["project"], ["name", "project_name", "project_type"], as_dict=True)
        if not p:
            frappe.throw(_("Project {0} not found.").format(payload["project"]))
        groups = [({"project": p.name, "project_name": p.project_name, "project_type": p.project_type or "Production",
                    "exists": True}, [{**ln, "mode": ln.get("mode") or "top_up"} for ln in lines])]
    else:
        info = item_info([ln["item"] for ln in lines])
        boms, _rows = bom_tree([ln["item"] for ln in lines], depth=1)
        by_project = {}
        for ln in lines:
            it = info.get(ln["item"])
            if not it:
                frappe.throw(_("Item {0} not found.").format(ln["item"]))
            sp = stock_project_for(it, ln["item"] in boms, settings, on)
            key = sp["project_name"]
            by_project.setdefault(key, (sp, []))[1].append({**ln, "mode": ln.get("mode") or "top_up"})
        groups = list(by_project.values())

    return [_propose_one(proj, lns, order_type, payload, cfg, on) for proj, lns in groups]


def _propose_one(proj, lines, order_type, payload, cfg, on):
    settings = cfg["doc"]
    rules = scenario_rules(proj["project_type"], order_type)
    roots = [ln["item"] for ln in lines]
    boms, rows = bom_tree(roots, chosen=payload.get("boms")) if rules["explode"] else ({}, {})
    codes = set(roots) | {c for rs in rows.values() for c, _q in rs}
    info = item_info(codes)
    lots = free_lots(codes)
    project = proj.get("project")
    held = held_for(project, codes)
    come, come_src = coming(project, codes)

    lot_projects = {l["project"] for ls in lots.values() for l in ls if l["project"]}
    kinds = dict(frappe.get_all("Project", filters={"name": ["in", list(lot_projects)]},
                                fields=["name", "planning_order_type"], as_list=True)) if lot_projects and _has("Project", "planning_order_type") else {}

    def is_own(lot):
        if order_type == MTO:
            return bool(project) and same_project(lot["project"], project)
        return (bool(project) and same_project(lot["project"], project)) or kinds.get(lot["project"]) == MTS

    def is_borrowable(lot):
        return lot["project"] and not lot["produced"] and kinds.get(lot["project"]) != MTO and not is_own(lot)

    groups = {}
    for code, it in info.items():
        groups[code] = it.item_group
    gbounds = {g.name: (g.lft, g.rgt) for g in frappe.get_all(
        "Item Group", filters={"name": ["in", list(set(groups.values()))]}, fields=["name", "lft", "rgt"])} if groups else {}

    data = {}
    own_lots, borrow_lots = {}, {}
    for code in codes:
        it = info.get(code) or frappe._dict()
        made = rules["explode"] and code in boms
        rule = deepest(gbounds.get(it.get("item_group")), cfg["rules"])
        round_to = 1.0 if made else (flt(rule.round_to) if rule and rule.round_to else cfg["round_to"])
        own_lots[code] = [l for l in lots.get(code, []) if is_own(l)]
        borrow_lots[code] = [l for l in lots.get(code, []) if is_borrowable(l)]
        data[code] = {"made": made, "bom": rows.get(code, []), "round_to": round_to,
                      "own": sum(l["qty"] for l in own_lots[code]) + flt(held.get(code)),
                      "coming": flt(come.get(code)), "borrowable": sum(l["qty"] for l in borrow_lots[code])}

    plan = build_plan(lines, data, rules)
    stage_rows = {(r.stage or "").strip().lower(): r for r in settings.stage_leads}
    made_codes = [c for c in boms]
    bom_options = defaultdict(list)
    loss_of = {}
    if made_codes:
        lf = ["process_loss_percentage"] if frappe.db.has_column("BOM", "process_loss_percentage") else []
        for b in frappe.get_all("BOM", filters={"item": ["in", made_codes], "is_active": 1, "docstatus": 1},
                                fields=["name", "item", "is_default"] + lf, order_by="is_default desc, modified desc"):
            bom_options[b.item].append(b.name)
            loss_of[b.name] = flt(b.get("process_loss_percentage"))
    routes = (payload.get("routes") or {})
    chosen_services = (payload.get("services") or {})
    previous = last_service([r["item"] for r in plan["levels"] if r["made"]])
    levels, reservations, requests, warnings = [], [], {"Manufacture": [], "Job work": [], "Purchase": []}, []
    needed_by = str(getdate(payload.get("needed_by") or add_days(today(), 30)))

    for r in plan["levels"]:
        code = r["item"]
        it = info.get(code) or frappe._dict(item_name=code, stock_uom="")
        stage = stage_of(code, it.get("item_group")) if r["made"] else ""
        srow = stage_rows.get(stage.lower()) if stage else None
        route = (routes.get(code) or (srow.route if srow and srow.route else "In-house")) if r["made"] else ""
        days_route = (cfg.get("stage_route_days") or {}).get(stage.lower(), {}).get(route) if r["made"] and stage else None
        options = [x.strip() for x in ((srow.get("job_work_services") if srow else "") or "").split(",") if x.strip()]
        if previous.get(code) and previous[code] not in options:
            options = [previous[code]] + options
        service = chosen_services.get(code) or previous.get(code) or (options[0] if options else None)

        # reservations: own stock for an order (not what is already held), and borrowed stock
        held_here = min(flt(held.get(code)), r["own"])
        if rules["reserve_own"] and r["own"] - held_here > EPS:
            picked, _miss = allocate_lots(own_lots[code], r["own"] - held_here)
            reservations += [{**l, "item_code": code, "kind": "own"} for l in picked]
        if r["reserve"] > EPS:
            picked, _miss = allocate_lots(borrow_lots[code], r["reserve"])
            reservations += [{**l, "item_code": code, "kind": "borrow"} for l in picked]

        if r["request"] > EPS:
            if r["made"] and route == "Job work":
                if service:
                    requests["Job work"].append({"item_code": service, "qty": r["request"], "bom_no": boms.get(code), "for_item": code})
                else:
                    warnings.append(_("{0}: job work, but no job-work service is set for stage {1} in Re-order Settings — "
                                      "planned as a Manufacture request instead.").format(code, stage))
                    requests["Manufacture"].append({"item_code": code, "qty": r["request"], "bom_no": boms.get(code)})
            elif r["made"]:
                requests["Manufacture"].append({"item_code": code, "qty": r["request"], "bom_no": boms.get(code)})
            else:
                requests["Purchase"].append({"item_code": code, "qty": r["request"]})

        levels.append({**{k: r[k] for k in ("item", "need", "own", "coming", "reserve", "short", "request", "made", "depth")},
                       "how": [t for _q, t in r["how"]], "item_name": it.get("item_name"), "uom": it.get("stock_uom"),
                       "stage": stage or ("Bought" if not r["made"] else ""), "route": route, "stage_days": days_route,
                       "service": service if r["made"] else None, "service_options": options if r["made"] else [],
                       "bom": boms.get(code) if r["made"] else None, "bom_options": bom_options.get(code, []) if r["made"] else [],
                       "process_loss": loss_of.get(boms.get(code), 0.0) if r["made"] else 0.0,
                       "service_from": ("this item's last job work" if previous.get(code) == service and service else
                                        "the stage's most common" if service else ""),
                       "coming_from": come_src.get(code, []), "held": held_here,
                       "reserve_from": sorted({l["project"] for l in borrow_lots[code]})[:3] if r["reserve"] > EPS else []})

    # bought levels: when the usual supplier would deliver an order placed today
    arrivals = bought_arrivals([l["item"] for l in levels if not l["made"]], info, gbounds, cfg)
    for l in levels:
        a = arrivals.get(l["item"])
        if l["made"] or not a:
            continue
        l.update(a)
        if l["request"] > EPS and a["arrives_by"] and getdate(a["arrives_by"]) > getdate(needed_by):
            who = a["supplier"] or _("its supplier")
            warnings.append(_("{0}: needed by {1}, but {2} usually takes {3} days, so an order placed today arrives "
                              "around {4}. Move Needed by, or buy from a faster supplier.").format(
                l["item"], needed_by, who, _days(a["lead_days"]), a["arrives_by"]))

    return {"project": proj, "order_type": order_type, "rules": rules, "needed_by": needed_by,
            "sales_order": payload.get("sales_order") if order_type == MTO else None,
            "lines": lines, "levels": levels, "reservations": reservations, "requests": requests, "warnings": warnings,
            "totals": {"own": sum(l["own"] for l in levels), "coming": sum(l["coming"] for l in levels),
                       "reserve": sum(l["reserve"] for l in levels),
                       "requests": sum(1 for k in requests if requests[k]), "request_lines": sum(len(v) for v in requests.values())}}


def _days(x):
    return int(x) if float(x).is_integer() else x


def bought_arrivals(codes, info, gbounds, cfg):
    """{item: {"lead_days", "arrives_by", "supplier", "lead_source"}} for bought items, with
    their usual supplier (Re-order Settings › Supplier lead days); arrives_by is None when no
    lead days are set anywhere."""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    from pranera_planning.lead_time import resolve

    def group_days(group):
        return flt(getattr(deepest(gbounds.get(group), cfg["rules"]), "bought_lead_days", 0) or 0)
    out = {}
    for code, r in resolve(codes, {c: info.get(c) or {} for c in codes}, group_days, cfg.get("lead")).items():
        out[code] = {"lead_days": r["days"], "arrives_by": str(add_days(today(), math.ceil(r["days"]))) if r["days"] else None,
                     "supplier": r["supplier"], "lead_source": r["text"]}
    return out


# ── create ────────────────────────────────────────────────────────────────────

def create(payload):
    """Rebuild the proposal(s) from fresh stock, then make each one's project (made to stock),
    reservations and draft Material Requests. One proposal fails as a whole."""
    out = []
    for prop in propose(payload):
        out.append(_create_one(prop))
    return out


def _warehouse_for(item, comp, settings):
    wh = frappe.db.get_value("Item Default", {"parent": item, "company": comp}, "default_warehouse")
    return wh or settings.get("default_warehouse") or frappe.db.get_single_value("Stock Settings", "default_warehouse")


def _create_one(prop):
    settings = frappe.get_single("Re-order Settings")
    comp = company()
    proj = prop["project"]
    project = proj.get("project")
    if not project:                                     # a new made-to-stock project
        doc = frappe.get_doc({"doctype": "Project", "project_name": proj["project_name"], "project_type": proj["project_type"],
                              "status": "Open", "company": comp,
                              **({"planning_order_type": MTS, "stock_family": proj.get("family"), "stock_period": proj.get("period")}
                                 if _has("Project", "planning_order_type") else {})})
        doc.insert()
        project = doc.name
    elif prop["order_type"] == MTO and _has("Project", "planning_order_type"):
        updates = {"planning_order_type": MTO}
        if prop.get("sales_order") and not frappe.db.get_value("Project", project, "sales_order"):
            updates["sales_order"] = prop["sales_order"]
            customer = frappe.db.get_value("Sales Order", prop["sales_order"], "customer")
            if customer and not frappe.db.get_value("Project", project, "customer"):
                updates["customer"] = customer
        frappe.db.set_value("Project", project, updates)

    if _has("Project", "saved_plan"):
        frappe.db.set_value("Project", project, "saved_plan", json.dumps({
            "saved_on": str(today()), "order_type": prop["order_type"], "needed_by": prop["needed_by"],
            "sales_order": prop.get("sales_order"),
            "lines": [{"item": ln["item"], "qty": flt(ln["qty"]), "mode": ln.get("mode") or "need"} for ln in prop["lines"]],
        }))

    made_res = []
    for r in prop["reservations"]:
        doc = frappe.get_doc({
            "doctype": "Project Stock Reservation", "purchase_project": r["project"], "production_project": project,
            "item_code": r["item_code"], "batch_no": r["batch_no"], "warehouse": r["warehouse"], "roll_no": r.get("roll_no") or "",
            "reserved_qty": r["qty"], "sales_order": prop.get("sales_order") or None,
            "remarks": _("From the plan of {0}").format(today()),
        })
        doc.insert()
        made_res.append(doc.name)

    made_mr = []
    kinds = {"Manufacture": "Manufacture", "Job work": "Purchase", "Purchase": "Purchase"}
    all_codes = {ln["item_code"] for lines in prop["requests"].values() for ln in lines}
    uoms = dict(frappe.get_all("Item", filters={"name": ["in", list(all_codes)]}, fields=["name", "stock_uom"], as_list=True)) if all_codes else {}
    for kind, lines in prop["requests"].items():
        if not lines:
            continue
        mr = frappe.get_doc({"doctype": "Material Request", "material_request_type": kinds[kind], "company": comp,
                             "transaction_date": today(), "schedule_date": prop["needed_by"]})
        if _has("Material Request", "for_project"):
            mr.for_project = project
        for ln in lines:
            uom = uoms.get(ln["item_code"])
            row = {"item_code": ln["item_code"], "qty": ln["qty"], "schedule_date": prop["needed_by"], "project": project,
                   "uom": uom, "stock_uom": uom, "conversion_factor": 1,
                   "warehouse": _warehouse_for(ln.get("for_item") or ln["item_code"], comp, settings)}
            if ln.get("bom_no"):
                row["bom_no"] = ln["bom_no"]
            if _has("Material Request Item", "for_project"):
                row["for_project"] = project
            mr.append("items", row)
        mr.insert()
        made_mr.append({"name": mr.name, "kind": kind, "lines": len(lines)})
    return {"project": project, "project_name": proj.get("project_name"), "reservations": made_res, "requests": made_mr}
