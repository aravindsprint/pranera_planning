"""Re-order engine: works out, per item, its average demand, lead days, re-order level and
quantity, where it stands now, and what to plan. Results go to Item Re-order Level (one
record per item), which the Stock levels and re-order report reads.

Runs nightly (hooks.scheduler_events) and on demand (recalculate_now). All reading is done in
bulk — one query per kind of number, never one per item. The arithmetic is in
reorder_math.py; see its docstring for the formulas.

Numbers, per item:
  demand     over Re-order Settings.history_days, read from the documents (the stock ledger
             took 38 s for 90 days on erp.pranera.in; these take under 1 s) —
             sales        Sales Invoices that update stock + Delivery Notes (returns subtract;
                          on live all sales go through Sales Invoices)
             consumption  Material Transfer for Manufacture / Manufacture / Send to
                          Subcontractor lines out of stores warehouses only (material is counted
                          when it leaves stores for WIP, not again when WIP is consumed)
  in stores  Bin balances in stores warehouses (not WIP / subcontractor: see
             reservation.warehouse_place)
  reserved   what active Project Stock Reservations still hold
  WIP        what open Work Orders and Subcontracting Orders are still expected to deliver
  on order   open Purchase Orders (not subcontracted) + submitted Material Requests not yet
             ordered (Purchase and Manufacture). Purchase Order lines due after today + the
             item's lead days are "arriving later": shown, but left out of Position, since an
             order placed today would arrive first
  lead days  the item's stage days (Re-order Settings › Days used) + the stages below it, down
             its default BOMs to its bought material — whose own lead days count only for the
             bought item itself, unless include_bought_lead_days is ticked. A bought item's
             lead days come from the ranked sources in Re-order Settings › Supplier lead days
             (its supplier's Supplier Items row, the supplier's usual lead days, the Item's Lead
             Time Days, the group rule), for its default supplier — see lead_time.py
"""
import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, getdate, now_datetime, today

from pranera_planning.lead_math import later_note, split_on_order
from pranera_planning.reorder_math import (
    cumulative_lead, deepest, main_input, median, normalise_family, reorder_numbers, stage_days_used,
)
from pranera_planning.reservation import ENFORCED_TYPES, _pool_clause, get_reservation_state, is_pool_warehouse, stage_of

CHUNK = 500
DONE = ("Completed", "Closed", "Cancelled", "Stopped")


def _chunks(xs, n=CHUNK):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield tuple(xs[i:i + n])


def _sum_by_item(query, items, extra=None):
    """Run a `... WHERE x IN %(items)s ... GROUP BY item` query over item chunks."""
    out = defaultdict(float)
    for chunk in _chunks(items):
        for item, qty in frappe.db.sql(query, {"items": chunk, **(extra or {})}):
            out[item] += flt(qty)
    return out


# ── settings ──────────────────────────────────────────────────────────────────

def load_settings():
    s = frappe.get_single("Re-order Settings")
    groups = {r.item_group for r in s.group_rules if r.item_group}
    bounds = {g.name: (g.lft, g.rgt) for g in frappe.get_all(
        "Item Group", filters={"name": ["in", list(groups)]}, fields=["name", "lft", "rgt"])} if groups else {}
    rules = [(*bounds[r.item_group], r) for r in s.group_rules if r.item_group in bounds]
    stage_days = stage_days_used([r.as_dict() for r in s.stage_leads], bool(s.get("use_learned_lead_days")))
    return {
        "doc": s,
        "history_days": int(s.history_days or 90),
        "near_margin": flt(s.near_margin if s.near_margin is not None else 10),
        "safety_days": flt(s.default_safety_days if s.default_safety_days is not None else 5),
        "cover_days": flt(s.default_cover_days if s.default_cover_days is not None else 30),
        "round_to": flt(s.default_round_to) or 1.0,
        "rules": rules,
        "stage_days": stage_days,
        "include_bought": bool(s.get("include_bought_lead_days")),
        "lead": lead_config(s),
    }


def lead_config(s):
    from pranera_planning.lead_time import load_config
    return load_config(s)


# ── the data ──────────────────────────────────────────────────────────────────

def demand(since, items=None):
    """({item: sales}, {item: consumption}) since `since`, from the documents. Without
    `items`, every item with any demand — that is how the nightly run finds what to calculate."""
    sales, used = defaultdict(float), defaultdict(float)
    item_clause = "AND {col} IN %(items)s" if items else ""
    clause, pool_values = _pool_clause("sed.s_warehouse")
    for chunk in (_chunks(items) if items else [None]):
        values = {"since": since, "items": chunk, "types": ENFORCED_TYPES, **pool_values}
        for item, qty in frappe.db.sql(
            f"""SELECT sii.item_code, SUM(sii.stock_qty) FROM `tabSales Invoice` si
                JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
                WHERE si.docstatus = 1 AND si.update_stock = 1 AND si.posting_date >= %(since)s
                  {item_clause.format(col="sii.item_code")}
                GROUP BY sii.item_code""", values):
            sales[item] += flt(qty)                       # returns carry negative quantities
        for item, qty in frappe.db.sql(
            f"""SELECT dni.item_code, SUM(dni.stock_qty) FROM `tabDelivery Note` dn
                JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
                WHERE dn.docstatus = 1 AND dn.posting_date >= %(since)s
                  {item_clause.format(col="dni.item_code")}
                GROUP BY dni.item_code""", values):
            sales[item] += flt(qty)
        for item, qty in frappe.db.sql(
            f"""SELECT sed.item_code, SUM(sed.transfer_qty) FROM `tabStock Entry` se
                JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
                WHERE se.docstatus = 1 AND se.posting_date >= %(since)s AND se.stock_entry_type IN %(types)s
                  AND IFNULL(sed.s_warehouse, '') <> '' AND IFNULL(sed.is_finished_item, 0) = 0
                  AND {clause} {item_clause.format(col="sed.item_code")}
                GROUP BY sed.item_code""", values):
            used[item] += flt(qty)
    return {k: max(0.0, v) for k, v in sales.items()}, dict(used)


def in_stores(items):
    out = defaultdict(float)
    for chunk in _chunks(items):
        for item, wh, qty in frappe.db.sql(
            "SELECT item_code, warehouse, actual_qty FROM `tabBin` WHERE item_code IN %(items)s AND actual_qty != 0",
            {"items": chunk}):
            if is_pool_warehouse(wh):
                out[item] += flt(qty)
    return out


def reserved(items):
    rows = frappe.get_all("Project Stock Reservation", filters={"status": "Active", "item_code": ["in", list(items)]},
                          fields=["name", "item_code", "batch_no"]) if items else []
    if not rows:
        return {}
    remaining = {r["name"]: r["remaining_qty"] for st in get_reservation_state({r.batch_no for r in rows}).values()
                 for r in st["reservations"]}
    out = defaultdict(float)
    for r in rows:
        out[r.item_code] += flt(remaining.get(r.name))
    return out


def wip(items):
    out = _sum_by_item(
        f"""SELECT production_item, SUM(GREATEST(qty - produced_qty, 0)) FROM `tabWork Order`
            WHERE docstatus = 1 AND status NOT IN {DONE} AND production_item IN %(items)s GROUP BY production_item""", items)
    for item, qty in _sum_by_item(
        f"""SELECT soi.item_code, SUM(GREATEST(soi.qty - soi.received_qty, 0) * IFNULL(NULLIF(soi.conversion_factor, 0), 1))
            FROM `tabSubcontracting Order Item` soi
            JOIN `tabSubcontracting Order` sco ON sco.name = soi.parent AND sco.docstatus = 1 AND sco.status NOT IN {DONE}
            WHERE soi.item_code IN %(items)s GROUP BY soi.item_code""", items).items():
        out[item] += qty
    return out


def open_po_lines(items):
    """[(item, open stock qty, Required By, Purchase Order)] of open, not subcontracted
    Purchase Orders — for splitting On order into in time and arriving later."""
    out = []
    for chunk in _chunks(items):
        out += [tuple(r) for r in frappe.db.sql(
            f"""SELECT poi.item_code, GREATEST(poi.qty - poi.received_qty, 0) * IFNULL(NULLIF(poi.conversion_factor, 0), 1),
                       poi.schedule_date, po.name
                FROM `tabPurchase Order Item` poi
                JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
                 AND po.status NOT IN {DONE + ('Delivered', 'On Hold')} AND IFNULL(po.is_subcontracted, 0) = 0
                WHERE poi.item_code IN %(items)s AND poi.qty > poi.received_qty""", {"items": chunk})]
    return out


def on_order(items):
    out = _sum_by_item(
        f"""SELECT poi.item_code, SUM(GREATEST(poi.qty - poi.received_qty, 0) * IFNULL(NULLIF(poi.conversion_factor, 0), 1))
            FROM `tabPurchase Order Item` poi
            JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
             AND po.status NOT IN {DONE + ('Delivered', 'On Hold')} AND IFNULL(po.is_subcontracted, 0) = 0
            WHERE poi.item_code IN %(items)s GROUP BY poi.item_code""", items)
    for item, qty in _sum_by_item(
        """SELECT mri.item_code, SUM(GREATEST(mri.stock_qty - mri.ordered_qty, 0)) FROM `tabMaterial Request Item` mri
           JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus = 1
            AND mr.status IN ('Pending', 'Partially Ordered') AND mr.material_request_type IN ('Purchase', 'Manufacture')
           WHERE mri.item_code IN %(items)s GROUP BY mri.item_code""", items).items():
        out[item] += qty
    return out


def bom_chain(items):
    """({made item: main input}, {made item}) following default BOMs down from `items`."""
    inputs, made, todo, seen = {}, set(), set(items), set()
    for _depth in range(8):
        todo -= seen
        if not todo:
            break
        seen |= todo
        boms = {}
        for chunk in _chunks(todo):
            for item, bom, uom in frappe.db.sql(
                """SELECT b.item, b.name, i.stock_uom FROM `tabBOM` b JOIN `tabItem` i ON i.name = b.item
                   WHERE b.item IN %(items)s AND b.is_default = 1 AND b.is_active = 1 AND b.docstatus = 1""", {"items": chunk}):
                boms[bom] = (item, uom)
        rows = defaultdict(list)
        for chunk in _chunks(boms):
            for bom, code, qty, uom, batch in frappe.db.sql(
                """SELECT bi.parent, bi.item_code, bi.stock_qty, i.stock_uom, i.has_batch_no FROM `tabBOM Item` bi
                   JOIN `tabItem` i ON i.name = bi.item_code WHERE bi.parent IN %(boms)s""", {"boms": chunk}):
                rows[bom].append((code, qty, uom, batch))
        todo = set()
        for bom, (item, uom) in boms.items():
            made.add(item)
            below = main_input(rows[bom], uom)
            if below:
                inputs[item] = below
                todo.add(below)
    return inputs, made


# ── the run ───────────────────────────────────────────────────────────────────

def recalculate_all():
    """Scheduler (daily): learn lead days, then recalculate every item with demand in the
    history window, or with a result from before (so it can drop to No demand)."""
    learn_lead_days()
    cfg = load_settings()
    since = add_days(today(), -cfg["history_days"])
    sales, used = demand(since)
    items = set(sales) | set(used) | set(frappe.get_all("Item Re-order Level", pluck="name"))
    items = set(frappe.get_all("Item", filters={"name": ["in", list(items)], "is_stock_item": 1, "disabled": 0}, pluck="name")) if items else set()
    count = calculate(items, cfg, sales=sales, used=used)
    frappe.db.set_single_value("Re-order Settings", {"last_run": now_datetime(), "last_run_items": count})
    frappe.db.commit()
    return count


@frappe.whitelist()
def recalculate_now():
    """The Re-order Settings button: run in the background, it can take a few minutes."""
    frappe.only_for(("System Manager", "Stock Manager", "Manufacturing Manager"))
    frappe.enqueue("pranera_planning.reorder.recalculate_all", queue="long", timeout=3600, job_id="pranera_reorder_recalculate",
                   deduplicate=True)
    return _("Recalculating in the background — the report updates when it finishes.")


def calculate(items, cfg, sales=None, used=None):
    """Work out and store the numbers for `items`. Returns how many were written."""
    items = sorted(items)
    if not items:
        return 0
    if sales is None or used is None:
        sales, used = demand(add_days(today(), -cfg["history_days"]), items)
    fields = ["name", "item_name", "item_group", "stock_uom", "lead_time_days"]
    if frappe.db.has_column("Item", "commercial_name"):
        fields.append("commercial_name")
    info = {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", items]}, fields=fields)}
    groups = {g.name: (g.lft, g.rgt) for g in frappe.get_all(
        "Item Group", filters={"name": ["in", list({i.item_group for i in info.values()})]}, fields=["name", "lft", "rgt"])}
    stores, held, making, ordered = in_stores(items), reserved(items), wip(items), on_order(items)
    inputs, made = bom_chain(items)
    below = set(inputs.values()) - set(info)
    bought_info = {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", list(below)]},
                                                     fields=["name", "item_group", "lead_time_days"])} if below else {}
    all_groups = set(groups) | {i.item_group for i in bought_info.values()}
    if all_groups - set(groups):
        groups.update({g.name: (g.lft, g.rgt) for g in frappe.get_all(
            "Item Group", filters={"name": ["in", list(all_groups - set(groups))]}, fields=["name", "lft", "rgt"])})

    def rule_for(group):
        return deepest(groups.get(group), cfg["rules"])

    stage_of_item = {i: stage_of(i, (info.get(i) or bought_info.get(i) or {}).get("item_group")) for i in set(info) | set(bought_info)}
    stage_days = {i: cfg["stage_days"].get(str(stage_of_item.get(i, "")).lower(), 0) for i in made}
    bought_days, bought_lead = bought_leads(
        {c: it for c, it in list(info.items()) + list(bought_info.items()) if c not in made},
        lambda group: flt(getattr(rule_for(group), "bought_lead_days", 0) or 0), cfg.get("lead"))

    item_lead = {code: cumulative_lead(code, stage_days, inputs, bought_days, cfg["include_bought"]) for code in items}
    later, later_lines = split_on_order(open_po_lines(items), today(), item_lead)

    now = now_datetime()
    written = 0
    for code in items:
        it = info.get(code)
        if not it:
            continue
        rule = rule_for(it.item_group)
        basis = (rule.demand_basis if rule and rule.demand_basis else "Sales + Consumption")
        qty = (sales.get(code, 0) if "Sales" in basis else 0) + (used.get(code, 0) if "Consumption" in basis else 0)
        lead = item_lead[code]
        arriving_later = min(flt(later.get(code)), flt(ordered.get(code)))
        safety_days = flt(rule.safety_days) if rule and rule.safety_days is not None and rule.safety_days != "" else cfg["safety_days"]
        cover_days = flt(rule.cover_days) if rule and rule.cover_days else cfg["cover_days"]
        round_to = flt(rule.round_to) if rule and rule.round_to else cfg["round_to"]
        n = reorder_numbers(qty, cfg["history_days"], lead, safety_days, cover_days,
                            stores.get(code, 0), held.get(code, 0), making.get(code, 0),
                            ordered.get(code, 0) - arriving_later,
                            round_to, cfg["near_margin"])
        family = normalise_family(it.get("commercial_name")) or _top_group(it.item_group)
        values = {
            "item_name": it.item_name, "item_group": it.item_group, "family": family,
            "stage": stage_of_item.get(code) if code in made else "", "obtained": "Made" if code in made else "Bought",
            "stock_uom": it.stock_uom, "demand_basis": basis, "demand_qty": qty, "lead_days": lead,
            "safety_days": safety_days, "cover_days": cover_days, "round_to": round_to,
            "in_stores": stores.get(code, 0), "reserved": held.get(code, 0), "wip": making.get(code, 0),
            "on_order": ordered.get(code, 0) - arriving_later, "arriving_later": arriving_later,
            "arriving_later_note": later_note(later_lines.get(code, []), it.stock_uom) if arriving_later else "",
            "supplier": (bought_lead.get(code) or {}).get("supplier") if code not in made else None,
            "lead_source": (bought_lead.get(code) or {}).get("text", "") if code not in made else "",
            "calculated_on": now, **n,
        }
        _save(code, values)
        written += 1
    return written


def bought_leads(info, group_days, lead_cfg=None):
    """({item: lead days}, {item: lead_time.resolve row}) for bought items."""
    from pranera_planning.lead_time import resolve
    rows = resolve(list(info), info, group_days, lead_cfg)
    return {code: r["days"] for code, r in rows.items()}, rows


_TOP = {}


def _top_group(group):
    """The top of an item's group tree below "All Item Groups" — the family fallback."""
    if not group:
        return ""
    if group not in _TOP:
        g = frappe.db.get_value("Item Group", group, ["lft", "rgt", "parent_item_group"], as_dict=True)
        top = group
        if g:
            chain = frappe.db.sql(
                """SELECT name, parent_item_group FROM `tabItem Group` WHERE lft <= %s AND rgt >= %s ORDER BY lft""",
                (g.lft, g.rgt), as_dict=True)
            top = next((c.name for c in chain if c.parent_item_group and not frappe.db.get_value(
                "Item Group", c.parent_item_group, "parent_item_group")), group)
        _TOP[group] = normalise_family(top)
    return _TOP[group]


def _save(code, values):
    if frappe.db.exists("Item Re-order Level", code):
        frappe.db.set_value("Item Re-order Level", code, values, update_modified=False)
    else:
        frappe.get_doc({"doctype": "Item Re-order Level", "item_code": code, **values}).insert(ignore_permissions=True)


# ── learning lead days ────────────────────────────────────────────────────────

def learn_lead_days():
    """Median days per stage and route over Re-order Settings.lead_history_months:
    in-house   Work Order creation → its last Manufacture entry
    job work   Subcontracting Order date → its last Subcontracting Receipt
    Fills the settings' stage rows (adding stages it finds), each row's usual route —
    whichever route has more orders — unless someone has already chosen it, and its job-work
    services (the services Purchase Material Requests bought against that stage's BOMs, most
    used first) where empty."""
    s = frappe.get_single("Re-order Settings")
    since = add_months(today(), -int(s.lead_history_months or 6))
    days = defaultdict(lambda: {"In-house": [], "Job work": []})
    for item, group, created, done in frappe.db.sql(
        """SELECT wo.production_item, i.item_group, wo.creation, MAX(se.posting_date)
           FROM `tabWork Order` wo JOIN `tabItem` i ON i.name = wo.production_item
           JOIN `tabStock Entry` se ON se.work_order = wo.name AND se.docstatus = 1 AND se.purpose = 'Manufacture'
           WHERE wo.docstatus = 1 AND wo.status = 'Completed' AND wo.creation >= %s
           GROUP BY wo.name""", since):
        days[stage_of(item, group)]["In-house"].append((getdate(done) - getdate(created)).days)
    for item, group, ordered, done in frappe.db.sql(
        """SELECT soi.item_code, i.item_group, sco.transaction_date, r.last_receipt
           FROM `tabSubcontracting Order` sco
           JOIN `tabSubcontracting Order Item` soi ON soi.parent = sco.name
           JOIN `tabItem` i ON i.name = soi.item_code
           JOIN (SELECT scri.subcontracting_order, MAX(scr.posting_date) last_receipt
                 FROM `tabSubcontracting Receipt Item` scri
                 JOIN `tabSubcontracting Receipt` scr ON scr.name = scri.parent AND scr.docstatus = 1
                 GROUP BY scri.subcontracting_order) r ON r.subcontracting_order = sco.name
           WHERE sco.docstatus = 1 AND sco.status = 'Completed' AND sco.transaction_date >= %s""", since):
        days[stage_of(item, group)]["Job work"].append((getdate(done) - getdate(ordered)).days)

    services = defaultdict(lambda: defaultdict(int))
    for item, group, svc, n in frappe.db.sql(
        """SELECT b.item, i.item_group, mri.item_code, COUNT(*) FROM `tabMaterial Request Item` mri
           JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus = 1
            AND mr.material_request_type = 'Purchase' AND mr.transaction_date >= %s
           JOIN `tabItem` si ON si.name = mri.item_code AND si.is_stock_item = 0
           JOIN `tabBOM` b ON b.name = mri.bom_no JOIN `tabItem` i ON i.name = b.item
           GROUP BY b.item, i.item_group, mri.item_code""", since):
        services[stage_of(item, group)][svc] += n

    rows = {(r.stage or "").strip().lower(): r for r in s.stage_leads}
    for stage, counts in services.items():
        row = rows.get(stage.lower())
        if row and not row.get("job_work_services"):
            ranked = [svc for svc, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n >= 5][:5]
            if ranked:
                row.job_work_services = ", ".join(ranked)
    for stage, routes in days.items():
        if not stage or stage == "Other":
            continue
        row = rows.get(stage.lower()) or s.append("stage_leads", {"stage": stage})
        row.inhouse_days, row.inhouse_orders = _rounded(median(routes["In-house"])), len(routes["In-house"])
        row.jobwork_days, row.jobwork_orders = _rounded(median(routes["Job work"])), len(routes["Job work"])
        if not row.route:
            row.route = "Job work" if row.jobwork_orders > row.inhouse_orders else "In-house"
    s.flags.ignore_permissions = True
    s.save()


def _rounded(x):
    return round(x, 1) if x is not None else None
