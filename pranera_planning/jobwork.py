"""Open job work counted under the item it makes.

A job-work order goes through three documents before it is a Subcontracting Order, and the first
two name the *service* (DRYER, KNITTING…), not the item:

    Purchase Material Request   line item = the service, bom_no = the BOM of the item it makes
    Purchase Order (subcontracted)  line item = the service, fg_item = the item it makes
    Subcontracting Order        line item = the item it makes (counted elsewhere)

Planning compares coming quantity by item, so without this a job-work request or a subcontracted
Purchase Order not yet turned into a Subcontracting Order looked like nothing coming: a re-plan
asked for the same job work again, and switching the item back to in-house asked for it twice.

Counted here:
  * Purchase Material Request lines for a non-stock item with a BOM: stock qty − ordered qty,
    while the request is open (drafts too, as for Manufacture requests);
  * subcontracted Purchase Order lines (fg_item set) whose line has no submitted Subcontracting
    Order yet: the finished-good quantity.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt

OPEN_MR = "('Stopped', 'Cancelled', 'Ordered', 'Transferred', 'Issued', 'Received')"
DONE_PO = "('Completed', 'Closed', 'Cancelled', 'Delivered', 'On Hold')"


def _has(doctype, field):
    return frappe.db.has_column(doctype, field)


def _for_project(project):
    """MR Item names of the project (project OR for_project, as two indexed lookups)."""
    names = [r[0] for r in frappe.db.sql(
        "SELECT name FROM `tabMaterial Request Item` WHERE project = %s AND IFNULL(bom_no, '') != ''", project) or []]
    if _has("Material Request Item", "for_project"):
        names += [r[0] for r in frappe.db.sql(
            "SELECT name FROM `tabMaterial Request Item` WHERE for_project = %s AND IFNULL(bom_no, '') != ''", project) or []]
    return tuple(set(names))


def request_lines(project, items):
    """[{mr, docstatus, row, item, service, open, cf, mr_ordered}] of the project's open job-work
    Purchase requests for `items` (the item each one makes), drafts first, newest first."""
    if not project or not items:
        return []
    rows = _for_project(project)
    if not rows:
        return []
    return frappe.db.sql(f"""SELECT mr.name mr, mr.docstatus, mri.name row, b.item item, mri.item_code service,
            GREATEST(mri.stock_qty - mri.ordered_qty, 0) open, IFNULL(NULLIF(mri.conversion_factor, 0), 1) cf,
            (SELECT IFNULL(SUM(x.ordered_qty), 0) FROM `tabMaterial Request Item` x WHERE x.parent = mr.name) mr_ordered
            FROM `tabMaterial Request Item` mri
            JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus < 2
             AND mr.material_request_type = 'Purchase' AND IFNULL(mr.status, '') NOT IN {OPEN_MR}
            JOIN `tabItem` s ON s.name = mri.item_code AND s.is_stock_item = 0
            JOIN `tabBOM` b ON b.name = mri.bom_no
            WHERE mri.name IN %(rows)s AND b.item IN %(items)s AND mri.stock_qty > mri.ordered_qty
            ORDER BY mr.docstatus ASC, mr.creation DESC""", {"rows": rows, "items": tuple(items)}, as_dict=True)


def po_lines(project, items):
    """[(item, qty, po)] subcontracted Purchase Order lines of the project for `items` that have
    no submitted Subcontracting Order yet."""
    if not project or not items or not _has("Purchase Order Item", "fg_item"):
        return []
    qty = "IFNULL(NULLIF(poi.fg_item_qty, 0), poi.stock_qty)" if _has("Purchase Order Item", "fg_item_qty") else "poi.stock_qty"
    return frappe.db.sql(f"""SELECT poi.fg_item, {qty}, po.name FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1 AND IFNULL(po.is_subcontracted, 0) = 1
         AND po.status NOT IN {DONE_PO}
        WHERE poi.project = %(p)s AND poi.fg_item IN %(items)s
          AND NOT EXISTS (SELECT 1 FROM `tabSubcontracting Order Item` soi
                          JOIN `tabSubcontracting Order` sco ON sco.name = soi.parent AND sco.docstatus = 1
                          WHERE soi.purchase_order_item = poi.name)""", {"p": project, "items": tuple(items)})


def coming(project, items):
    """({item: qty}, {item: [text]}) of open job work for `items` not yet on a Subcontracting Order."""
    qty, src = defaultdict(float), defaultdict(list)
    by_item = defaultdict(set)
    for r in request_lines(project, items):
        qty[r.item] += flt(r.open)
        by_item[r.item].add(r.mr)
    for item, names in by_item.items():
        src[item].append(f"Job-work requests: {len(names)}")
    pos = defaultdict(set)
    for item, q, po in po_lines(project, items):
        if flt(q) > 0:
            qty[item] += flt(q)
            pos[item].add(po)
    for item, names in pos.items():
        src[item].append(f"Job-work Purchase Orders: {len(names)}")
    return qty, src


def on_order(items):
    """{item: qty} of open job work for `items` across all projects (re-order levels): submitted
    job-work Purchase requests not yet ordered, and subcontracted Purchase Order lines with no
    submitted Subcontracting Order yet."""
    out = defaultdict(float)
    if not items:
        return out
    for item, q in frappe.db.sql("""SELECT b.item, SUM(GREATEST(mri.stock_qty - mri.ordered_qty, 0))
            FROM `tabBOM` b
            JOIN `tabMaterial Request Item` mri ON mri.bom_no = b.name
            JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus = 1
             AND mr.material_request_type = 'Purchase' AND mr.status IN ('Pending', 'Partially Ordered')
            JOIN `tabItem` s ON s.name = mri.item_code AND s.is_stock_item = 0
            WHERE b.item IN %(items)s GROUP BY b.item""", {"items": tuple(items)}):
        out[item] += flt(q)
    if _has("Purchase Order Item", "fg_item"):
        qty = "IFNULL(NULLIF(poi.fg_item_qty, 0), poi.stock_qty)" if _has("Purchase Order Item", "fg_item_qty") else "poi.stock_qty"
        for item, q in frappe.db.sql(f"""SELECT poi.fg_item, SUM({qty}) FROM `tabPurchase Order Item` poi
                JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1 AND IFNULL(po.is_subcontracted, 0) = 1
                 AND po.status NOT IN {DONE_PO}
                WHERE poi.fg_item IN %(items)s
                  AND NOT EXISTS (SELECT 1 FROM `tabSubcontracting Order Item` soi
                                  JOIN `tabSubcontracting Order` sco ON sco.name = soi.parent AND sco.docstatus = 1
                                  WHERE soi.purchase_order_item = poi.name)
                GROUP BY poi.fg_item""", {"items": tuple(items)}):
            out[item] += flt(q)
    return out
