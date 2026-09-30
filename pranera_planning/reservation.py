"""Project stock reservation: the rule that stock reserved for one production project
cannot be used by another, and the Stock Entry hook that enforces it.

Covers any batch-tracked item. A reservation is held at a stock location:
  yarn and other batch items          warehouse + batch
  fabric, collar, cuff (roll items)   warehouse + batch + roll
Roll items are items under the FABRIC item group tree (collars and cuffs live there too);
see roll_item_groups(). Roll numbers are read from Stock Entry Detail's roll field.

Definitions
-----------
available   qty of a batch sitting in issuable warehouses, i.e. everything except
            WIP and subcontractor warehouses — recognised by how Work Orders and
            Subcontracting Orders use them (see non_pool_warehouses), plus names starting
            WIP / SUB / Direct Delivery. Batch.batch_qty is NOT used: it counts stock in
            every warehouse, including WIP.
issue       a Stock Entry source line that takes a batch out of that pool:
            Material Transfer for Manufacture, Manufacture (straight from stores) and
            Send to Subcontractor. Its project is the Work Order's project; for Send to
            Subcontractor, the project of the Subcontracting Order item the line supplies
            material for, or else of the Purchase Order item behind it (see
            PROJECT_EXPR). This covers Job Card-triggered
            transfers too — a Job Card doesn't move stock itself, it triggers a Stock
            Entry of one of these same types, which is what this hook actually sees.
remaining   reserved_qty minus everything issued to that project from that batch, out of
            that warehouse (and, for a roll reservation, that roll) since the reservation
            was created.
free        per warehouse: available there minus remaining over its active reservations.

owner       a batch *produced* for a project — finished item of a Manufacture Stock Entry
            (Work Order's project, else the entry's), or received on a Subcontracting
            Receipt (its item's project, else the Subcontracting Order / Purchase Order
            item's) — belongs to that project. Purchased batches have no owner: they are
            shared until reserved. A batch produced for several projects has no owner.

An issue of qty q from warehouse W to project P is allowed when
q <= free at W + remaining reserved for P at W — where "free" counts only if P owns the
batch or nobody does; and a roll reserved for another project cannot be issued to P at
all (beyond any unreserved balance left on that roll). Batches with no active reservation
and no owner are never touched by this module.

A reservation is Fulfilled automatically once everything reserved has been issued (on
Stock Entry submit), and goes back to Active if cancelling that entry reopens it.

Site config (all optional)
--------------------------
project_stock_reservation_enforcement                  0 switches enforcement off (default 1)
project_stock_reservation_use_reserved_first          "block" (default) / "warn" / "off": while a project
                                                       has reserved stock of an item waiting, it must issue
                                                       that item from the reservation (batch, warehouse, roll)
project_stock_reservation_protect_produced             0 lets produced batches go to any project
                                                       without a reservation (default 1)
project_stock_reservation_stages                       [[item code prefix, stage], ...] for the
                                                       page's produced section, default
                                                       [["GKF","Knitting"],["DKF","Dyeing"],["SKF","Finishing"]]
project_stock_reservation_excluded_warehouse_prefixes  list, default ["WIP", "SUB", "Direct Delivery"]
project_stock_reservation_excluded_warehouses          list of extra warehouses whose stock is committed
project_stock_reservation_pool_warehouses              list of warehouses to always treat as stores
project_stock_reservation_roll_item_groups             list, default ["FABRIC", "COLLAR", "CUFF"]
                                                       (item group trees reserved by roll; missing
                                                       groups are ignored)
project_stock_reservation_roll_field                   Stock Entry Detail field holding the roll no.,
                                                       default "custom_roll_no"
"""
import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from pranera_planning.reservation_math import (
    EPS, allocate_issues, allowed_issue_qty, clean_roll, place_packed_rolls, remaining_qty, reserved_first,
    same_project,
)

ENFORCED_TYPES = ("Material Transfer for Manufacture", "Send to Subcontractor", "Manufacture")
DEFAULT_EXCLUDED_PREFIXES = ("WIP", "SUB", "Direct Delivery")
DEFAULT_ROLL_ITEM_GROUPS = ("FABRIC", "COLLAR", "CUFF")
DEFAULT_ROLL_FIELD = "custom_roll_no"
DEFAULT_STAGES = (("GKF", "Knitting"), ("DKF", "Dyeing"), ("SKF", "Finishing"))

# Which project does a Stock Entry line belong to?
#
# Send to Subcontractor (Purchase Order -> Subcontracting Order -> Stock Entry), first hit:
#   1. the line's own order row: Stock Entry Detail.sco_rm_detail -> Subcontracting Order
#      Supplied Item -> its Subcontracting Order Item's project, else that item's Purchase
#      Order Item's project. Exact per line, so an order spanning projects is fine.
#   2. the whole Subcontracting Order, if its items (SCO project, else PO item project)
#      name exactly one project; then the SCO / Purchase Order header project.
#   3. an old-style entry against a Purchase Order directly: its items' single project,
#      else its header project.
#   4. the entry's own project.
# (On erp.pranera.in the header projects are blank and SCO item / PO item projects are
# always filled and agree, so 1 decides practically every line.)
#
# Everything else: Work Order project, then the entry's own project.
_SCO_ITEM_PROJECT = "COALESCE(NULLIF(soi.project, ''), NULLIF(poi.project, ''))"
PROJECT_EXPR = f"""
CASE
  WHEN se.stock_entry_type = 'Send to Subcontractor' THEN COALESCE(
    (SELECT {_SCO_ITEM_PROJECT}
       FROM `tabSubcontracting Order Supplied Item` sosi
       JOIN `tabSubcontracting Order Item` soi ON soi.name = sosi.reference_name
       LEFT JOIN `tabPurchase Order Item` poi ON poi.name = soi.purchase_order_item
      WHERE sosi.name = sed.sco_rm_detail LIMIT 1),
    (SELECT MAX({_SCO_ITEM_PROJECT})
       FROM `tabSubcontracting Order Item` soi
       LEFT JOIN `tabPurchase Order Item` poi ON poi.name = soi.purchase_order_item
      WHERE soi.parent = se.subcontracting_order
     HAVING COUNT(DISTINCT {_SCO_ITEM_PROJECT}) = 1),
    (SELECT COALESCE(NULLIF(sco.project, ''), NULLIF(po.project, ''))
       FROM `tabSubcontracting Order` sco
       LEFT JOIN `tabPurchase Order` po ON po.name = sco.purchase_order
      WHERE sco.name = se.subcontracting_order),
    (SELECT MAX(NULLIF(poi.project, '')) FROM `tabPurchase Order Item` poi
      WHERE poi.parent = se.purchase_order
     HAVING COUNT(DISTINCT NULLIF(poi.project, '')) = 1),
    (SELECT NULLIF(po.project, '') FROM `tabPurchase Order` po WHERE po.name = se.purchase_order),
    NULLIF(se.project, '')
  )
  ELSE COALESCE(NULLIF(wo.project, ''), NULLIF(se.project, ''))
END
"""


# ── configuration ────────────────────────────────────────────────────────────
def is_enabled():
    return bool(int(frappe.conf.get("project_stock_reservation_enforcement", 1)))


def excluded_prefixes():
    return tuple(frappe.conf.get("project_stock_reservation_excluded_warehouse_prefixes") or DEFAULT_EXCLUDED_PREFIXES)


def reserved_first_mode():
    """"block" (default), "warn" or "off": a project must issue an item from its own
    reservation while that reservation still has stock waiting."""
    mode = str(frappe.conf.get("project_stock_reservation_use_reserved_first") or "block").lower()
    return mode if mode in ("block", "warn", "off") else "block"


def protect_produced():
    return bool(int(frappe.conf.get("project_stock_reservation_protect_produced", 1)))


def stages():
    return [tuple(x) for x in (frappe.conf.get("project_stock_reservation_stages") or DEFAULT_STAGES)]


def stage_of(item_code, item_group=None, operation=None):
    """Stage label for a produced batch: the operation that made it ("KNITTING" -> "Knitting")
    if known, else the configured item code prefix label, else the item group."""
    if operation:
        return operation.title() if operation.isupper() else operation
    for prefix, label in stages():
        if (item_code or "").upper().startswith(prefix.upper()):
            return label
    return item_group or "Other"


def stage_rank(item_code):
    """Position in the process by item code prefix (GKF 0, DKF 1, SKF 2, ...), 99 if unknown.
    Stages of the same rank (Knitting, Collar Knitting, Cuff Knitting) run side by side."""
    for i, (prefix, _) in enumerate(stages()):
        if (item_code or "").upper().startswith(prefix.upper()):
            return i
    return 99


def roll_item_groups():
    return tuple(frappe.conf.get("project_stock_reservation_roll_item_groups") or DEFAULT_ROLL_ITEM_GROUPS)


def roll_field():
    return frappe.conf.get("project_stock_reservation_roll_field") or DEFAULT_ROLL_FIELD


def _roll_expr(alias="sed"):
    """SQL for the roll no. on a Stock Entry Detail row, or NULL on a site without the field."""
    field = roll_field()
    if not frappe.db.has_column("Stock Entry Detail", field):
        return "NULL"
    return f"{alias}.`{field}`"


def roll_tracked_items(item_codes):
    """The subset of item_codes reserved by roll (item group inside a roll_item_groups() tree)."""
    item_codes = list({i for i in item_codes if i})
    if not item_codes:
        return set()
    return set(frappe.db.sql_list(
        """SELECT DISTINCT i.name FROM `tabItem` i
           JOIN `tabItem Group` ig ON ig.name = i.item_group
           JOIN `tabItem Group` root ON root.name IN %(roots)s
           WHERE i.name IN %(items)s AND ig.lft >= root.lft AND ig.rgt <= root.rgt""",
        {"roots": roll_item_groups(), "items": tuple(item_codes)},
    ))


def is_roll_item(item_code):
    return item_code in roll_tracked_items([item_code])


WAREHOUSE_CACHE_KEY = "pranera_planning:reservation:non_pool_warehouses"
PREFIX_LABELS = {"WIP": "In WIP", "SUB": "At subcontractor"}


def non_pool_warehouses():
    """{warehouse: "In WIP" | "At subcontractor" | "Excluded"} — warehouses whose stock is
    already committed to production, so it is never free, reservable or "in stores".

    Found from how warehouses are used, not their names (on erp.pranera.in most WIP
    warehouses — "DYE/UNDER DYEING (WIP)", the knitting machines "SJ05-FUKUHARA ...",
    "SM01-SUEDING SECTION" — don't start with "WIP"):
      In WIP            a warehouse Work Orders use as WIP (where it differs from that
                        order's source and target) more often than they draw from or
                        deliver into it, or one used as WIP whose name says WIP / Work In
                        Progress; plus Manufacturing Settings' default WIP warehouse
      At subcontractor  a Subcontracting Order's (or subcontracted Purchase Order's)
                        supplier warehouse
      Excluded          listed in site config project_stock_reservation_excluded_warehouses
    Site config project_stock_reservation_pool_warehouses forces warehouses back in.
    The name prefixes in excluded_prefixes() apply on top of this.

    Cached for an hour; cleared when a Work Order or Subcontracting Order is submitted.
    """
    cache = frappe.cache()
    found = cache.get_value(WAREHOUSE_CACHE_KEY)
    if found is not None:
        return found

    def counts(q):
        return {w: n for w, n in frappe.db.sql(q) if w}

    as_wip = counts("""SELECT wip_warehouse, COUNT(*) FROM `tabWork Order`
                       WHERE docstatus = 1 AND wip_warehouse <> IFNULL(source_warehouse, '')
                         AND wip_warehouse <> IFNULL(fg_warehouse, '')
                       GROUP BY wip_warehouse""")
    as_feed = defaultdict(int)
    for q in (
        """SELECT source_warehouse, COUNT(*) FROM `tabWork Order`
           WHERE docstatus = 1 AND source_warehouse <> IFNULL(wip_warehouse, '') GROUP BY source_warehouse""",
        """SELECT fg_warehouse, COUNT(*) FROM `tabWork Order`
           WHERE docstatus = 1 AND fg_warehouse <> IFNULL(wip_warehouse, '') GROUP BY fg_warehouse""",
        """SELECT woi.source_warehouse, COUNT(DISTINCT woi.parent) FROM `tabWork Order Item` woi
           JOIN `tabWork Order` wo ON wo.name = woi.parent AND wo.docstatus = 1
           WHERE woi.source_warehouse <> IFNULL(wo.wip_warehouse, '') GROUP BY woi.source_warehouse""",
    ):
        for w, n in counts(q).items():
            as_feed[w] += n

    # Mostly used as WIP (a few old orders drawing from it don't make it a store:
    # "DYE/UNDER DYEING (WIP)" 4566 vs 5), or named as one ("Work In Progress - PSS").
    wip = {w for w, n in as_wip.items() if n > as_feed.get(w, 0) or _looks_like_wip(w)}
    default_wip = frappe.db.get_single_value("Manufacturing Settings", "default_wip_warehouse")
    if default_wip:
        wip.add(default_wip)
    sql = lambda q: {w for w in frappe.db.sql_list(q) if w}
    subcontractor = (
        sql("SELECT DISTINCT supplier_warehouse FROM `tabSubcontracting Order` WHERE docstatus = 1")
        | sql("SELECT DISTINCT supplier_warehouse FROM `tabPurchase Order` WHERE docstatus = 1 AND is_subcontracted = 1")
    )

    found = {w: "In WIP" for w in wip}
    found.update({w: "At subcontractor" for w in subcontractor})
    found.update({w: "Excluded" for w in frappe.conf.get("project_stock_reservation_excluded_warehouses") or []})
    for w in frappe.conf.get("project_stock_reservation_pool_warehouses") or []:
        found.pop(w, None)

    cache.set_value(WAREHOUSE_CACHE_KEY, found, expires_in_sec=3600)
    return found


def _looks_like_wip(warehouse):
    return bool(re.search(r"\bWIP\b|WORK IN PROGRESS", warehouse or "", re.I))


def clear_warehouse_cache(doc=None, method=None):
    """doc_events hook: a newly submitted Work Order / Subcontracting Order may name a new
    WIP or supplier warehouse."""
    frappe.cache().delete_value(WAREHOUSE_CACHE_KEY)


def warehouse_place(warehouse):
    """Where stock in `warehouse` is: None if issuable ("in stores"), else a label."""
    if not warehouse:
        return None
    label = non_pool_warehouses().get(warehouse)
    if label:
        return label
    w = warehouse.lower()
    for p in excluded_prefixes():
        if w.startswith(p.lower()):
            return PREFIX_LABELS.get(p, p)
    return None


def is_pool_warehouse(warehouse):
    return warehouse_place(warehouse) is None


def _pool_clause(column):
    """SQL fragment + params keeping only rows whose warehouse is inside the issuable pool."""
    parts, values = [], {}
    for i, prefix in enumerate(excluded_prefixes()):
        key = f"wh_prefix_{i}"
        parts.append(f"{column} NOT LIKE %({key})s")
        values[key] = prefix.replace("%", r"\%").replace("_", r"\_") + "%"
    committed = tuple(non_pool_warehouses())
    if committed:
        parts.append(f"{column} NOT IN %(wh_committed)s")
        values["wh_committed"] = committed
    return " AND ".join(parts) or "1=1", values


# ── queries ──────────────────────────────────────────────────────────────────
def get_batch_purchase_project(batch_no):
    """Project the batch was purchased under (from submitted Purchase Receipt items)."""
    return frappe.db.sql(
        """SELECT MIN(pri.project) FROM `tabPurchase Receipt Item` pri
           JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
           WHERE pri.batch_no = %s AND IFNULL(pri.project, '') <> ''""",
        batch_no,
    )[0][0]


# Project a produced batch-entry belongs to. Needs aliases se, sed, wo (Stock Entry side) and
# scri, scr, soi, poi (Subcontracting Receipt side), all LEFT JOINed on the bundle's voucher.
_PRODUCED_JOINS = """
    LEFT JOIN `tabStock Entry` se ON sbb.voucher_type = 'Stock Entry' AND se.name = sbb.voucher_no
    LEFT JOIN `tabStock Entry Detail` sed ON sbb.voucher_type = 'Stock Entry' AND sed.name = sbb.voucher_detail_no
    LEFT JOIN `tabWork Order` wo ON wo.name = se.work_order
    LEFT JOIN `tabSubcontracting Receipt Item` scri
      ON sbb.voucher_type = 'Subcontracting Receipt' AND scri.name = sbb.voucher_detail_no
    LEFT JOIN `tabSubcontracting Receipt` scr ON scr.name = scri.parent
    LEFT JOIN `tabSubcontracting Order Item` soi ON soi.name = scri.subcontracting_order_item
    LEFT JOIN `tabPurchase Order Item` poi
      ON poi.name = COALESCE(NULLIF(scri.purchase_order_item, ''), soi.purchase_order_item)
"""
_PRODUCED_WHERE = """
    sbe.qty > 0 AND sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND (
      (sbb.voucher_type = 'Stock Entry' AND se.docstatus = 1 AND se.purpose = 'Manufacture'
        AND sed.is_finished_item = 1)
      OR (sbb.voucher_type = 'Subcontracting Receipt' AND scr.docstatus = 1)
    )
"""
_PRODUCED_PROJECT = """
    CASE WHEN sbb.voucher_type = 'Stock Entry'
      THEN COALESCE(NULLIF(wo.project, ''), NULLIF(se.project, ''))
      ELSE COALESCE(NULLIF(scri.project, ''), NULLIF(soi.project, ''), NULLIF(poi.project, ''), NULLIF(scr.project, ''))
    END
"""


def get_produced_owners(batch_nos):
    """{batch: project} for batches produced for exactly one project (see "owner")."""
    batch_nos = list({b for b in batch_nos if b})
    if not batch_nos:
        return {}
    rows = frappe.db.sql(
        f"""SELECT sbe.batch_no, {_PRODUCED_PROJECT} AS project
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            {_PRODUCED_JOINS}
            WHERE sbe.batch_no IN %(batches)s AND {_PRODUCED_WHERE}""",
        {"batches": tuple(batch_nos)}, as_dict=True,
    )
    seen = defaultdict(set)
    for r in rows:
        seen[r.batch_no].add(r.project or "")
    return {b: next(iter(ps)) for b, ps in seen.items() if len(ps) == 1 and next(iter(ps))}


def get_produced_batches(project):
    """Batches produced for `project`: [{item_code, item_name, item_group, stock_uom, batch_no,
    produced_qty, made_by}]. Made by its Work Orders (Manufacture) or its Subcontracting
    Receipts (via the receipt item's project, else its Subcontracting Order / Purchase Order
    item's)."""
    # Look the vouchers up first with simple indexed queries: an OR of the two routes in one
    # query stops MariaDB using any index (2.8 s vs ~0.2 s on erp.pranera.in).
    wos = frappe.db.sql_list("SELECT name FROM `tabWork Order` WHERE project = %s AND docstatus = 1", project)
    entries = set(frappe.db.sql_list(
        """SELECT name FROM `tabStock Entry` WHERE docstatus = 1 AND purpose = 'Manufacture'
           AND project = %s AND IFNULL(work_order, '') = ''""", project,
    ))
    if wos:
        entries |= set(frappe.db.sql_list(
            """SELECT name FROM `tabStock Entry` WHERE docstatus = 1 AND purpose = 'Manufacture'
               AND work_order IN %(wos)s""", {"wos": tuple(wos)},
        ))
    sco_items = frappe.db.sql_list(
        """SELECT soi.name FROM `tabSubcontracting Order Item` soi
           LEFT JOIN `tabPurchase Order Item` poi ON poi.name = soi.purchase_order_item
           WHERE soi.project = %(p)s OR poi.project = %(p)s""",
        {"p": project},
    )
    receipt_items = set(frappe.db.sql_list(
        "SELECT name FROM `tabSubcontracting Receipt Item` WHERE project = %s", project,
    ))
    if sco_items:
        receipt_items |= set(frappe.db.sql_list(
            "SELECT name FROM `tabSubcontracting Receipt Item` WHERE subcontracting_order_item IN %(i)s",
            {"i": tuple(sco_items)},
        ))

    rows = []
    if entries:
        rows += frappe.db.sql(
            """SELECT sed.item_code, SUM(sbe.qty) AS qty, sbe.batch_no, 'Work Order' AS made_by
               FROM `tabStock Entry Detail` sed
               JOIN `tabSerial and Batch Bundle` sbb
                 ON sbb.voucher_type = 'Stock Entry' AND sbb.voucher_no = sed.parent AND sbb.voucher_detail_no = sed.name
                AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
               JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sbb.name AND sbe.qty > 0
               WHERE sed.parent IN %(entries)s AND sed.is_finished_item = 1
               GROUP BY sed.item_code, sbe.batch_no""",
            {"entries": tuple(entries)}, as_dict=True,
        )
    if receipt_items:
        rows += frappe.db.sql(
            """SELECT scri.item_code, SUM(sbe.qty) AS qty, sbe.batch_no, 'Subcontracting' AS made_by
               FROM `tabSubcontracting Receipt Item` scri
               JOIN `tabSubcontracting Receipt` scr ON scr.name = scri.parent AND scr.docstatus = 1
               JOIN `tabSerial and Batch Bundle` sbb
                 ON sbb.voucher_type = 'Subcontracting Receipt' AND sbb.voucher_no = scr.name AND sbb.voucher_detail_no = scri.name
                AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
               JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sbb.name AND sbe.qty > 0
               WHERE scri.name IN %(items)s
               GROUP BY scri.item_code, sbe.batch_no""",
            {"items": tuple(receipt_items)}, as_dict=True,
        )
    if not rows:
        return []

    items = {
        i.name: i for i in frappe.get_all(
            "Item", filters={"name": ["in", list({r.item_code for r in rows})]},
            fields=["name", "item_name", "item_group", "stock_uom"],
        )
    }
    merged = {}
    for r in rows:
        key = (r.item_code, r.batch_no)
        m = merged.setdefault(key, frappe._dict(
            item_code=r.item_code, batch_no=r.batch_no, produced_qty=0.0, made_by=set(),
            item_name=items.get(r.item_code, {}).get("item_name"),
            item_group=items.get(r.item_code, {}).get("item_group"),
            stock_uom=items.get(r.item_code, {}).get("stock_uom"),
        ))
        m.produced_qty += flt(r.qty)
        m.made_by.add(r.made_by)
    out = []
    for m in merged.values():
        m.made_by = " + ".join(sorted(m.made_by))
        m.produced_qty = round(m.produced_qty, 3)
        out.append(m)
    return sorted(out, key=lambda m: (m.item_code, m.batch_no))


def batch_source_project(batch_no):
    """Whose stock a batch is, for reserving it: the project it was purchased under, else
    the one it was produced for."""
    return get_batch_purchase_project(batch_no) or get_produced_owners([batch_no]).get(batch_no)


def get_elsewhere_qty(batch_nos):
    """{batch: {label: qty}} held outside issuable warehouses — "In WIP", "At subcontractor",
    "Excluded" or an excluded name prefix (see warehouse_place)."""
    if not batch_nos:
        return {}
    clause, values = _pool_clause("sbe.warehouse")
    values["batches"] = tuple(batch_nos)
    rows = frappe.db.sql(
        f"""SELECT sbe.batch_no, sbe.warehouse, SUM(sbe.qty) AS qty
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            WHERE sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbe.batch_no IN %(batches)s
              AND NOT ({clause})
            GROUP BY sbe.batch_no, sbe.warehouse""",
        values, as_dict=True,
    )
    out = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if flt(r.qty) > EPS:
            out[r.batch_no][warehouse_place(r.warehouse) or "Elsewhere"] += flt(r.qty)
    return {b: {k: round(v, 3) for k, v in places.items()} for b, places in out.items()}


def get_available_qty(batch_nos):
    if not batch_nos:
        return {}
    clause, values = _pool_clause("sbe.warehouse")
    values["batches"] = tuple(batch_nos)
    rows = frappe.db.sql(
        f"""SELECT sbe.batch_no, SUM(sbe.qty) AS qty
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            WHERE sbb.docstatus = 1 AND sbb.is_cancelled = 0
              AND sbe.batch_no IN %(batches)s AND {clause}
            GROUP BY sbe.batch_no""",
        values, as_dict=True,
    )
    out = {b: 0.0 for b in batch_nos}
    out.update({r.batch_no: flt(r.qty) for r in rows})
    return out


def get_stock_locations(batch_nos):
    """{batch: {warehouse: {"available", "rolls", "rolls_uncertain"}}} over issuable warehouses.

    rolls  {roll_no: qty} numbered rolls in that warehouse, from two sources:
      1. the stock ledger — the roll no. on the Stock Entry line behind each bundle entry
         (joined by voucher_detail_no, the Stock Entry Detail row name). A roll the ledger
         has seen follows the ledger.
      2. submitted Roll Packing Lists (the knitting roll register) for rolls the ledger has
         never seen — batches move on as a whole without roll numbers, so this is the only
         record of which rolls a batch holds. They are placed in the stores warehouse the
         batch sits in, preferring the one the linked Stock Entry delivered to.
    rolls_uncertain  True when those rolls add up to more than is still unnumbered there:
      part of the batch left without roll numbers, so some listed rolls may be gone.
    """
    if not batch_nos:
        return {}
    rows = frappe.db.sql(
        f"""SELECT sbe.batch_no, sbe.warehouse, {_roll_expr()} AS roll_no, SUM(sbe.qty) AS qty
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            LEFT JOIN `tabStock Entry Detail` sed
              ON sbb.voucher_type = 'Stock Entry' AND sed.name = sbb.voucher_detail_no
            WHERE sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbe.batch_no IN %(batches)s
            GROUP BY sbe.batch_no, sbe.warehouse, roll_no""",
        {"batches": tuple(batch_nos)}, as_dict=True,
    )
    out = {b: {} for b in batch_nos}
    seen = defaultdict(set)                  # batch -> every roll no. the ledger has moved
    for r in rows:
        roll = clean_roll(r.roll_no)
        if roll:
            seen[r.batch_no].add(roll)
        if not is_pool_warehouse(r.warehouse):
            continue
        loc = out.setdefault(r.batch_no, {}).setdefault(
            r.warehouse, {"available": 0.0, "rolls": defaultdict(float), "rolls_uncertain": False})
        loc["available"] += flt(r.qty)
        if roll:
            loc["rolls"][roll] += flt(r.qty)

    # A roll whose reservation is Fulfilled has been issued — even when the issue line named
    # no roll — so it isn't in stores any more.
    for r in frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Fulfilled", "batch_no": ["in", list(batch_nos)], "roll_no": ["is", "set"]},
        fields=["batch_no", "roll_no"],
    ):
        seen[r.batch_no].add(clean_roll(r.roll_no))

    # Rolls moved on a pick list follow their last move: into another stores warehouse, or
    # out of stores (issued / at a subcontractor / in WIP).
    for batch, moves in get_pick_list_moves(batch_nos).items():
        last = {}
        for m in moves:
            last[m["roll_no"]] = m
        locs = out.get(batch) or {}
        for roll, m in last.items():
            if roll in seen[batch]:
                continue
            seen[batch].add(roll)
            wh = m["t_warehouse"]
            if wh in locs and m["weight"] > EPS:
                locs[wh]["rolls"][roll] += m["weight"]

    for batch, packed in get_packing_list_rolls(batch_nos).items():
        locs = out.get(batch) or {}
        room = {
            wh: loc["available"] - sum(q for q in loc["rolls"].values() if q > EPS)
            for wh, loc in locs.items()
        }
        placed, uncertain = place_packed_rolls(room, packed, seen[batch])
        for wh, rolls in placed.items():
            for roll, weight in rolls.items():
                locs[wh]["rolls"][roll] += weight
            locs[wh]["rolls_uncertain"] = wh in uncertain

    for locs in out.values():
        for loc in locs.values():
            loc["rolls"] = dict(loc["rolls"])
    return out


def get_packing_list_rolls(batch_nos):
    """{batch: [(roll_no, weight, warehouse the linked Stock Entry delivered the batch to)]}
    from submitted Roll Packing Lists."""
    if not batch_nos or not frappe.db.exists("DocType", "Roll Packing List"):
        return {}
    rows = frappe.db.sql(
        """SELECT rpli.batch, rpli.roll_no, rpli.roll_weight,
                  (SELECT sed.t_warehouse FROM `tabStock Entry Detail` sed
                    WHERE sed.parent = rpl.stock_entry AND sed.batch_no = rpli.batch
                      AND IFNULL(sed.t_warehouse, '') <> '' LIMIT 1) AS target
           FROM `tabRoll Packing List Item` rpli
           JOIN `tabRoll Packing List` rpl ON rpl.name = rpli.parent AND rpl.docstatus = 1
           WHERE rpli.batch IN %(batches)s
           ORDER BY rpl.posting_date, rpli.idx""",
        {"batches": tuple(batch_nos)}, as_dict=True,
    )
    out, dup = defaultdict(list), set()
    for r in rows:
        roll = clean_roll(r.roll_no)
        if roll and (r.batch, roll) not in dup and flt(r.roll_weight) > 0:
            dup.add((r.batch, roll))
            out[r.batch].append((roll, flt(r.roll_weight), r.target))
    return out


PICK_LINK_FIELDS = ("custom_roll_wise_pick_list", "roll_wise_pick_list")


def _pick_link_fields():
    return [f for f in PICK_LINK_FIELDS if frappe.db.has_column("Stock Entry", f)]


def get_pick_list_moves(batch_nos):
    """{batch: [{"roll_no", "weight", "voucher", "s_warehouse", "t_warehouse"}]} in posting
    order: rolls moved by submitted Stock Entries that carry a submitted Roll Wise Pick List
    (Stock Entry.custom_roll_wise_pick_list / roll_wise_pick_list, or the pick list's own
    stock_entry). The entry's line for that batch says where the rolls went; no target means
    they were issued (consumed, or sent to a subcontractor's warehouse counts as a target
    outside stores)."""
    batch_nos = list({b for b in batch_nos if b})
    if not batch_nos or not frappe.db.exists("DocType", "Roll Wise Pick List"):
        return {}
    picks = frappe.db.sql(
        """SELECT pi.parent AS pick, pi.batch, pi.roll_no, pi.roll_weight, pi.qty, p.stock_entry
           FROM `tabRoll Wise Pick Item` pi
           JOIN `tabRoll Wise Pick List` p ON p.name = pi.parent AND p.docstatus = 1
           WHERE pi.batch IN %(batches)s""",
        {"batches": tuple(batch_nos)}, as_dict=True,
    )
    if not picks:
        return {}
    pick_names = tuple({x.pick for x in picks})
    entries = {}                                   # entry name -> row, with .picks
    for field in _pick_link_fields():
        for e in frappe.db.sql(
            f"""SELECT name, posting_date, posting_time, creation, `{field}` AS pick
                FROM `tabStock Entry` WHERE docstatus = 1 AND `{field}` IN %(p)s""",
            {"p": pick_names}, as_dict=True,
        ):
            entries.setdefault(e.name, e).setdefault("picks", set()).add(e.pick)
    direct = {x.stock_entry for x in picks if x.stock_entry} - set(entries)
    if direct:
        for e in frappe.db.sql(
            """SELECT name, posting_date, posting_time, creation FROM `tabStock Entry`
               WHERE docstatus = 1 AND name IN %(n)s""", {"n": tuple(direct)}, as_dict=True,
        ):
            entries[e.name] = e
            e["picks"] = {x.pick for x in picks if x.stock_entry == e.name}
    if not entries:
        return {}
    lines = defaultdict(dict)                      # (entry, batch) -> {"s", "t"}
    for parent, batch, s_wh, t_wh in frappe.db.sql(
        """SELECT parent, batch_no, s_warehouse, t_warehouse FROM `tabStock Entry Detail`
           WHERE parent IN %(e)s AND batch_no IN %(b)s""",
        {"e": tuple(entries), "b": tuple(batch_nos)},
    ):
        lines[(parent, batch)] = {"s": s_wh, "t": t_wh}

    out = defaultdict(list)
    for name, e in sorted(entries.items(), key=lambda kv: (kv[1].posting_date, str(kv[1].posting_time), kv[1].creation)):
        for x in picks:
            roll = clean_roll(x.roll_no)
            if x.pick not in e["picks"] or not roll or (name, x.batch) not in lines:
                continue
            line = lines[(name, x.batch)]
            out[x.batch].append({
                "roll_no": roll, "weight": flt(x.roll_weight) or flt(x.qty), "voucher": name,
                "s_warehouse": line["s"], "t_warehouse": line["t"],
            })
    return out


def get_batch_operations(batch_nos):
    """{batch: operation that produced it}: the Job Card operation on its Roll Packing List
    (KNITTING, COLLAR KNITTING, ...), else the last operation of the Work Order whose
    Manufacture entry produced it."""
    batch_nos = list({b for b in batch_nos if b})
    if not batch_nos:
        return {}
    out = {}
    if frappe.db.exists("DocType", "Roll Packing List"):
        for batch, op in frappe.db.sql(
            """SELECT rpli.batch, MAX(jc.operation)
               FROM `tabRoll Packing List Item` rpli
               JOIN `tabRoll Packing List` rpl ON rpl.name = rpli.parent AND rpl.docstatus = 1
               JOIN `tabJob Card` jc ON rpl.document_type = 'Job Card' AND jc.name = rpl.document_name
               WHERE rpli.batch IN %(batches)s AND IFNULL(jc.operation, '') <> ''
               GROUP BY rpli.batch""",
            {"batches": tuple(batch_nos)},
        ):
            out[batch] = op
    missing = [b for b in batch_nos if b not in out]
    if missing:
        for batch, op in frappe.db.sql(
            """SELECT sbe.batch_no,
                      (SELECT woo.operation FROM `tabWork Order Operation` woo
                        WHERE woo.parent = se.work_order ORDER BY woo.idx DESC LIMIT 1)
               FROM `tabSerial and Batch Entry` sbe
               JOIN `tabSerial and Batch Bundle` sbb
                 ON sbb.name = sbe.parent AND sbb.voucher_type = 'Stock Entry'
                AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
               JOIN `tabStock Entry` se ON se.name = sbb.voucher_no AND se.purpose = 'Manufacture'
               JOIN `tabStock Entry Detail` sed ON sed.name = sbb.voucher_detail_no AND sed.is_finished_item = 1
               WHERE sbe.batch_no IN %(batches)s AND sbe.qty > 0 AND IFNULL(se.work_order, '') <> ''""",
            {"batches": tuple(missing)},
        ):
            if op and batch not in out:
                out[batch] = op
    return out


def get_issue_lines(batch_nos):
    """Every submitted issue of these batches:
    [{batch_no, warehouse, roll_no, project, qty, creation}].

    Read from Serial and Batch Entry (batch_no is indexed there; it is not on Stock Entry
    Detail, which made this query scan the whole table). Only outward entries count, so
    finished-goods and target-warehouse lines are excluded automatically.
    """
    if not batch_nos:
        return []
    clause, values = _pool_clause("sbe.warehouse")
    values.update(batches=tuple(batch_nos), types=ENFORCED_TYPES)
    lines = frappe.db.sql(
        f"""SELECT sbe.batch_no, sbe.warehouse, {_roll_expr()} AS roll_no, {PROJECT_EXPR} AS project,
                   ABS(sbe.qty) AS qty, se.creation AS creation, se.name AS voucher
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
            JOIN `tabStock Entry` se ON se.name = sbb.voucher_no
            LEFT JOIN `tabStock Entry Detail` sed ON sed.name = sbb.voucher_detail_no
            LEFT JOIN `tabWork Order` wo ON wo.name = se.work_order
            WHERE sbe.batch_no IN %(batches)s AND sbe.qty < 0
              AND sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbb.voucher_type = 'Stock Entry'
              AND se.docstatus = 1 AND se.stock_entry_type IN %(types)s
              AND {clause}""",
        values, as_dict=True,
    )
    for l in lines:
        l.roll_no = clean_roll(l.roll_no)
    return _split_by_pick_lists(lines, batch_nos)


def _split_by_pick_lists(lines, batch_nos):
    """An issue line naming no roll, on an entry whose pick list names the rolls for that
    batch, becomes one line per picked roll (anything left over stays unnumbered)."""
    if not any(not l.roll_no for l in lines):
        return lines
    picked = defaultdict(list)                     # (entry, batch) -> [(roll, weight)]
    for batch, moves in get_pick_list_moves(batch_nos).items():
        for m in moves:
            picked[(m["voucher"], batch)].append((m["roll_no"], m["weight"]))
    out = []
    for l in lines:
        rolls = picked.get((l.voucher, l.batch_no)) if not l.roll_no else None
        if not rolls:
            out.append(l)
            continue
        qty = flt(l.qty)
        for roll, weight in rolls:
            take = min(qty, weight)
            if take > EPS:
                out.append(frappe._dict(l, roll_no=roll, qty=take))
                qty -= take
        if qty > EPS:
            out.append(frappe._dict(l, qty=qty))
    return out


def get_reservation_state(batch_nos, exclude=None, issue_lines=None, statuses=("Active",)):
    """{batch: {"available", "locations", "reservations"}} for the given batches.

    available     total in issuable warehouses
    locations     {warehouse: {"available", "rolls"}}, see get_stock_locations()
    reservations  each with warehouse, roll_no, issued_qty and remaining_qty. issued_qty is
                  what was issued to its project from that batch and warehouse since it was
                  created — for a roll reservation, lines naming that roll plus its share of
                  lines naming no roll (see reservation_math.allocate_issues).
    `exclude` is a reservation name to leave out (used when validating that reservation).
    `statuses` defaults to Active only — the only ones that hold stock.
    """
    batch_nos = list(dict.fromkeys(b for b in batch_nos if b))
    if not batch_nos:
        return {}
    locations = get_stock_locations(batch_nos)
    # Active and Fulfilled always take part in working out what was issued against what, so
    # an old issue can't be counted again against a newer reservation; only `statuses` are
    # returned.
    reservations = frappe.get_all(
        "Project Stock Reservation",
        filters={"status": ["in", sorted(set(statuses) | {"Active", "Fulfilled"})], "batch_no": ["in", batch_nos]},
        fields=["name", "status", "batch_no", "warehouse", "roll_no", "production_project", "reserved_qty", "creation"],
    )
    lines = issue_lines if issue_lines is not None else get_issue_lines(batch_nos)

    state = {
        b: {
            "available": sum(l["available"] for l in locations.get(b, {}).values()),
            "locations": locations.get(b, {}),
            "reservations": [],
        }
        for b in batch_nos
    }
    groups = defaultdict(list)
    for r in reservations:
        groups[(r.batch_no, r.warehouse, (r.production_project or "").casefold())].append(r)
    issued = {}
    for (batch, wh, project), rs in groups.items():
        issued.update(allocate_issues(
            [{"name": r.name, "roll_no": clean_roll(r.roll_no), "reserved_qty": flt(r.reserved_qty), "creation": r.creation}
             for r in rs],
            [{"roll_no": l.roll_no, "qty": flt(l.qty), "creation": l.creation}
             for l in lines
             if l.batch_no == batch and l.warehouse == wh and same_project(l.project, rs[0].production_project)],
        ))

    for r in reservations:
        if (exclude and r.name == exclude) or r.status not in statuses:
            continue
        state[r.batch_no]["reservations"].append({
            "name": r.name,
            "status": r.status,
            "production_project": r.production_project,
            "warehouse": r.warehouse,
            "roll_no": clean_roll(r.roll_no),
            "reserved_qty": flt(r.reserved_qty),
            "issued_qty": issued[r.name],
            "remaining_qty": remaining_qty(r.reserved_qty, issued[r.name]),
        })
    return state


def reservations_at(state, warehouse):
    """The reservations in one batch's state that sit at `warehouse`."""
    return [r for r in state["reservations"] if r["warehouse"] == warehouse]


# ── Stock Entry hook ─────────────────────────────────────────────────────────
def resolve_project(doc):
    """The entry-level project: Work Order's, or the entry's own. For Send to Subcontractor,
    what applies to lines with no order row of their own — see line_projects()."""
    if doc.stock_entry_type == "Send to Subcontractor":
        return _subcontract_order_project(doc)
    project = frappe.db.get_value("Work Order", doc.work_order, "project") if doc.get("work_order") else None
    return project or doc.get("project") or None


def _subcontract_order_project(doc):
    """Steps 2-4 of PROJECT_EXPR for one Stock Entry."""
    if doc.get("subcontracting_order"):
        projects = frappe.db.sql_list(
            f"""SELECT DISTINCT {_SCO_ITEM_PROJECT} AS p
                FROM `tabSubcontracting Order Item` soi
                LEFT JOIN `tabPurchase Order Item` poi ON poi.name = soi.purchase_order_item
                WHERE soi.parent = %s AND {_SCO_ITEM_PROJECT} IS NOT NULL""",
            doc.subcontracting_order,
        )
        if len(projects) == 1:
            return projects[0]
        sco_project, po = frappe.db.get_value("Subcontracting Order", doc.subcontracting_order, ["project", "purchase_order"]) or (None, None)
        header = sco_project or (frappe.db.get_value("Purchase Order", po, "project") if po else None)
        if header:
            return header
    if doc.get("purchase_order"):
        projects = frappe.db.sql_list(
            """SELECT DISTINCT project FROM `tabPurchase Order Item`
               WHERE parent = %s AND IFNULL(project, '') <> ''""",
            doc.purchase_order,
        )
        if len(projects) == 1:
            return projects[0]
        header = frappe.db.get_value("Purchase Order", doc.purchase_order, "project")
        if header:
            return header
    return doc.get("project") or None


def line_projects(doc):
    """{row.name: project} for every item row of a Stock Entry.

    Send to Subcontractor rows take the project of their own Subcontracting Order item
    (or its Purchase Order item) via sco_rm_detail, falling back to the entry-level
    project; every other type uses the entry-level project for all rows.
    """
    fallback = resolve_project(doc)
    out = {row.name: fallback for row in doc.items}
    if doc.stock_entry_type != "Send to Subcontractor":
        return out
    details = [row.get("sco_rm_detail") for row in doc.items if row.get("sco_rm_detail")]
    if details:
        per_detail = dict(frappe.db.sql(
            f"""SELECT sosi.name, {_SCO_ITEM_PROJECT}
                FROM `tabSubcontracting Order Supplied Item` sosi
                JOIN `tabSubcontracting Order Item` soi ON soi.name = sosi.reference_name
                LEFT JOIN `tabPurchase Order Item` poi ON poi.name = soi.purchase_order_item
                WHERE sosi.name IN %(names)s""",
            {"names": tuple(set(details))},
        ))
        for row in doc.items:
            p = per_detail.get(row.get("sco_rm_detail"))
            if p:
                out[row.name] = p
    return out


def validate_stock_entry(doc, method=None):
    """doc_events hook: Stock Entry.validate.

    Only a deliberate ValidationError stops the entry. Any other failure in this module is
    logged and the entry is let through, so a bug here can never halt the shop floor.
    """
    if not is_enabled() or doc.stock_entry_type not in ENFORCED_TYPES:
        return
    try:
        _check(doc)
        _check_reserved_first(doc)
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(title="Project stock reservation check failed (entry allowed through)")
        frappe.msgprint(
            _("The stock reservation check could not run, so this entry was not checked against "
              "reservations. Please report it — details are in the Error Log "
              "(\"Project stock reservation check failed\")."),
            title=_("Reservation check skipped"), indicator="orange",
        )


def _row_batches(row):
    """Batches a Stock Entry row moves: its batch_no, else every batch in its bundle."""
    if row.get("batch_no"):
        return [row.batch_no]
    if row.get("serial_and_batch_bundle"):
        return frappe.get_all("Serial and Batch Entry", filters={"parent": row.serial_and_batch_bundle}, pluck="batch_no")
    return []


def _row_roll_parts(doc, rows):
    """{row.name: [(roll_no, qty)]} for the entry being saved: the row's own roll no., else
    the rolls its Roll Wise Pick List names for that batch (draft or submitted), else one
    unnumbered part."""
    field = roll_field()
    pick = next((doc.get(f) for f in PICK_LINK_FIELDS if doc.get(f)), None)
    picked = defaultdict(list)
    if pick and frappe.db.exists("DocType", "Roll Wise Pick List"):
        for batch, roll, weight, qty in frappe.db.sql(
            """SELECT pi.batch, pi.roll_no, pi.roll_weight, pi.qty FROM `tabRoll Wise Pick Item` pi
               JOIN `tabRoll Wise Pick List` p ON p.name = pi.parent AND p.docstatus < 2
               WHERE p.name = %s ORDER BY pi.idx""", pick,
        ):
            if clean_roll(roll):
                picked[batch].append((clean_roll(roll), flt(weight) or flt(qty)))
    out = {}
    for row in rows:
        qty = flt(row.transfer_qty or row.qty)
        own = clean_roll(row.get(field))
        if own or not picked.get(row.batch_no):
            out[row.name] = [(own, qty)]
            continue
        parts = []
        for roll, weight in picked[row.batch_no]:
            take = min(qty, weight)
            if take > EPS:
                parts.append((roll, take))
                qty -= take
        if qty > EPS:
            parts.append(("", qty))
        out[row.name] = parts
    return out


def _check(doc):
    field = roll_field()
    rows = [
        row for row in doc.items
        if row.batch_no and row.s_warehouse and not row.is_finished_item and is_pool_warehouse(row.s_warehouse)
    ]
    if not rows:
        return
    batches = list({r.batch_no for r in rows})

    # Fast path: most batches have no reservation and no owner.
    reserved_batches = set(frappe.get_all(
        "Project Stock Reservation",
        filters={"status": "Active", "batch_no": ["in", batches]},
        pluck="batch_no",
    ))
    owners = get_produced_owners(batches) if protect_produced() else {}
    if not reserved_batches and not owners:
        return

    projects = line_projects(doc)
    parts = _row_roll_parts(doc, rows)
    requested = defaultdict(float)          # (batch, warehouse, project) -> qty
    requested_roll = defaultdict(float)     # (batch, warehouse, roll, project) -> qty
    for row in rows:
        project = projects.get(row.name)
        if not project or (row.batch_no not in reserved_batches and row.batch_no not in owners):
            continue
        for roll, qty in parts[row.name]:
            requested[(row.batch_no, row.s_warehouse, project)] += qty
            if roll:
                requested_roll[(row.batch_no, row.s_warehouse, roll, project)] += qty
    if not requested:
        return

    state = get_reservation_state({key[0] for key in requested})
    problems = []

    for (batch, wh, project), qty in requested.items():
        st = state.get(batch)
        res = reservations_at(st, wh) if st else []
        owner = owners.get(batch)
        foreign = bool(owner) and not same_project(owner, project)
        if not res and not foreign:
            continue
        loc = st["locations"].get(wh, {"available": 0.0, "rolls": {}})
        allowed, free, own, total = allowed_issue_qty(loc["available"], res, project, owner=owner)
        if qty <= allowed + EPS:
            continue
        if foreign:
            problems.append(_(
                "<b>{0}</b> in {1} was produced for project <b>{2}</b>. Issuing {3:g} to {4} needs a "
                "reservation for {4} on the Stock Reservation page (reserved for {4} here: {5:g})."
            ).format(batch, wh, owner, qty, project, own))
        else:
            problems.append(_(
                "<b>{0}</b> in {1}: issuing {2:g} to project {3}, but only {4:g} can go to it "
                "(unreserved {5:g} + reserved for {3} {6:g}). Reserved for other projects: {7}."
            ).format(batch, wh, qty, project, allowed, free, own, _others(res, project)))

    for (batch, wh, roll, project), qty in requested_roll.items():
        st = state.get(batch)
        res = reservations_at(st, wh) if st else []
        on_roll = [r for r in res if r["roll_no"] == roll]
        owner = owners.get(batch)
        foreign = bool(owner) and not same_project(owner, project)
        if not on_roll and not foreign:
            continue
        loc = st["locations"].get(wh, {"available": 0.0, "rolls": {}})
        allowed = allowed_issue_qty(loc["available"], res, project, loc["rolls"], roll, owner=owners.get(batch))[0]
        if qty <= allowed + EPS:
            continue
        if foreign and not any(same_project(r["production_project"], project) for r in on_roll):
            problems.append(_(
                "<b>{0}</b> roll <b>{1}</b> in {2} was produced for project <b>{3}</b> and is not reserved "
                "for {4}. Reserve that roll for {4} on the Stock Reservation page first."
            ).format(batch, roll, wh, owner, project))
        else:
            problems.append(_(
                "<b>{0}</b> roll <b>{1}</b> in {2}: only {3:g} of it can go to project {4}. Reserved for others: {5}."
            ).format(batch, roll, wh, allowed, project, _others(on_roll, project)))

    if problems:
        frappe.throw(
            "<br>".join(problems),
            title=_("This stock is reserved for another project"),
        )


# ── fulfilment ─────────────────────────────────────────────────────────────────

def update_fulfilment(doc, method=None):
    """doc_events hook: Stock Entry on_submit / on_cancel.

    An Active reservation whose reserved qty has all been issued becomes Fulfilled; a
    Fulfilled one that is short again (the issuing entry was cancelled) goes back to Active.
    Runs on every enforced-type entry that touched a batch with such a reservation.

    On cancel the entry itself is left out explicitly: depending on the order in which the
    cancel updates the entry and its batch bundles, it can still look submitted while this
    hook runs.
    """
    if doc.stock_entry_type not in ENFORCED_TYPES:
        return
    batches = {b for row in doc.items if row.s_warehouse for b in _row_batches(row) if b}
    if batches:
        refresh_fulfilment(batches, exclude_voucher=doc.name if doc.docstatus == 2 else None)


def refresh_fulfilment(batch_nos, exclude_voucher=None):
    """Re-derive Active / Fulfilled for every reservation on these batches."""
    batch_nos = list(batch_nos)
    if not batch_nos or not frappe.db.exists(
        "Project Stock Reservation", {"status": ["in", ["Active", "Fulfilled"]], "batch_no": ["in", batch_nos]}
    ):
        return
    lines = [l for l in get_issue_lines(batch_nos) if l.voucher != exclude_voucher]
    state = get_reservation_state(batch_nos, issue_lines=lines, statuses=("Active", "Fulfilled"))
    for st in state.values():
        for r in st["reservations"]:
            done = r["issued_qty"] > EPS and r["remaining_qty"] <= EPS
            if r["status"] == "Active" and done:
                frappe.db.set_value("Project Stock Reservation", r["name"],
                                    {"status": "Fulfilled", "fulfilled_on": frappe.utils.now_datetime()})
            elif r["status"] == "Fulfilled" and not done:
                frappe.db.set_value("Project Stock Reservation", r["name"], {"status": "Active", "fulfilled_on": None})


def refresh_all_fulfilment():
    """Scheduler (daily): safety net re-deriving Active / Fulfilled for every open reservation."""
    batches = frappe.get_all("Project Stock Reservation", filters={"status": ["in", ["Active", "Fulfilled"]]},
                             pluck="batch_no", distinct=True)
    for i in range(0, len(batches), 200):
        refresh_fulfilment(batches[i:i + 200])
    frappe.db.commit()


# ── preview: what the produced-stock rule would block ─────────────────────────

def preview_produced_conflicts(days=30):
    """Submitted issue lines in the last `days` that took a batch produced for one project
    and gave it to another, with no reservation. Read-only; run with
      bench --site <site> execute pranera_planning.reservation.preview_produced_conflicts --kwargs "{'days': 30}"
    """
    lines = frappe.db.sql(
        f"""SELECT se.name AS stock_entry, se.posting_date, se.stock_entry_type, sed.batch_no,
                   sed.s_warehouse, sed.transfer_qty AS qty, {PROJECT_EXPR} AS project
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON se.name = sed.parent
            LEFT JOIN `tabWork Order` wo ON wo.name = se.work_order
            WHERE se.docstatus = 1 AND se.posting_date >= DATE_SUB(CURDATE(), INTERVAL %(days)s DAY)
              AND se.stock_entry_type IN %(types)s AND IFNULL(sed.batch_no, '') <> ''
              AND IFNULL(sed.s_warehouse, '') <> '' AND IFNULL(sed.is_finished_item, 0) = 0""",
        {"days": int(days), "types": ENFORCED_TYPES}, as_dict=True,
    )
    lines = [l for l in lines if is_pool_warehouse(l.s_warehouse) and l.project]
    owners = get_produced_owners([l.batch_no for l in lines])
    out = [
        {**l, "produced_for": owners[l.batch_no]}
        for l in lines
        if l.batch_no in owners and not same_project(owners[l.batch_no], l.project)
    ]
    summary = {"issue_lines_checked": len(lines), "would_need_reservation": len(out),
               "batches": len({l["batch_no"] for l in out})}
    print(frappe.as_json(summary))
    return out


def _check_reserved_first(doc):
    """A project that still has reserved stock of an item waiting must issue that item from
    its reservation — the reserved batch, from the reserved warehouse (and the reserved roll)
    — not from other free stock. Issuing more than is reserved is fine once the reserved
    stock is all being used. A reservation whose stock is no longer at its location is not
    insisted on. See reservation_math.reserved_first.
    """
    mode = reserved_first_mode()
    if mode == "off":
        return
    field = roll_field()
    rows = [
        row for row in doc.items
        if row.batch_no and row.s_warehouse and not row.is_finished_item and is_pool_warehouse(row.s_warehouse)
    ]
    if not rows:
        return
    projects = line_projects(doc)
    wanted = {(projects.get(r.name) or "").casefold() for r in rows} - {""}
    if not wanted:
        return
    reservations = [
        r for r in frappe.get_all(
            "Project Stock Reservation",
            filters={"status": "Active", "item_code": ["in", list({r.item_code for r in rows})]},
            fields=["name", "production_project", "item_code", "batch_no", "warehouse", "roll_no"],
        )
        if (r.production_project or "").casefold() in wanted
    ]
    if not reservations:
        return

    state = get_reservation_state({r.batch_no for r in reservations})
    remaining = {x["name"]: x["remaining_qty"] for st in state.values() for x in st["reservations"]}

    groups = defaultdict(lambda: {"reservations": [], "lines": [], "project": None})
    for r in reservations:
        loc = state.get(r.batch_no, {}).get("locations", {}).get(r.warehouse, {"available": 0.0, "rolls": {}})
        roll = clean_roll(r.roll_no)
        on_hand = loc["rolls"].get(roll, loc["available"]) if roll else loc["available"]
        g = groups[(r.production_project.casefold(), r.item_code)]
        g["project"] = r.production_project
        g["reservations"].append({
            "name": r.name, "batch_no": r.batch_no, "warehouse": r.warehouse, "roll_no": roll,
            "usable_qty": max(0.0, min(remaining.get(r.name, 0.0), on_hand)),
        })
    parts = _row_roll_parts(doc, rows)
    for row in rows:
        key = ((projects.get(row.name) or "").casefold(), row.item_code)
        if key in groups:
            for roll, qty in parts[row.name]:
                groups[key]["lines"].append({
                    "batch_no": row.batch_no, "warehouse": row.s_warehouse, "roll_no": roll, "qty": qty,
                })

    problems = []
    for (_project_key, item), g in groups.items():
        if not g["lines"]:
            continue
        result = reserved_first(g["reservations"], g["lines"])
        if not result["breach"]:
            continue
        where = "<br>".join(
            f"&nbsp;&nbsp;{r['name']}: {r['usable_qty']:g} of batch <b>{r['batch_no']}</b> in {r['warehouse']}"
            + (f", roll {r['roll_no']}" if r["roll_no"] else "")
            for r in g["reservations"] if r["usable_qty"] > EPS
        )
        problems.append(_(
            "Project <b>{0}</b> has {1:g} of <b>{2}</b> reserved and waiting, but this entry issues {3:g} "
            "from other stock. Issue it from the reservation first:<br>{4}<br>"
            "(or release the reservation on the Stock Reservation page if it is no longer needed)."
        ).format(g["project"], result["usable"], item, result["outside"], where))

    if not problems:
        return
    if mode == "block":
        frappe.throw("<br><br>".join(problems), title=_("Use the reserved stock first"))
    frappe.msgprint("<br><br>".join(problems), title=_("Reserved stock is waiting"), indicator="orange")


def _others(reservations, project):
    return ", ".join(
        f"{r['production_project']}: {r['remaining_qty']:g}"
        for r in reservations
        if r["remaining_qty"] > EPS and not same_project(r["production_project"], project)
    ) or "-"
