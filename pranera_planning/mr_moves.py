"""Moving quantity between a project's in-house and job-work requests.

A plan level already covered by the project's own Manufacture request (say dyeing, requested
in-house) can be switched to job work for part or all of it, and a level covered by a job-work
Purchase request can be switched back to in-house the same way. The plan then counts that much
less as coming and raises it on the other route instead; on Create the request it came from is
reduced by the same quantity (reduce(..., source)):

    draft request       its line is reduced (removed at 0; an empty request is deleted)
    submitted request   cancelled (one per item, all of it moved: just cancelled) or amended with
                        the reduced line and the amendment submitted —
                        only while nothing on it has been made into a Work Order yet; otherwise
                        refused, with the Work Order to reduce instead
                        (for a job-work request: while nothing on it is on a Purchase Order)
Drafts are reduced before submitted requests, newest first.
source is "Manufacture" (the in-house requests) or "Job work" (the job-work Purchase requests,
whose line names the service and whose BOM names the item it makes).
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

EPS = 1e-6


def _proj_clause():
    has = frappe.db.has_column("Material Request Item", "for_project")
    return "(mri.project = %(p)s" + (" OR mri.for_project = %(p)s)" if has else ")")


MANUFACTURE, JOB_WORK = "Manufacture", "Job work"


def open_lines(project, items, source=MANUFACTURE):
    """{item: [{"mr", "docstatus", "row", "open", "cf", "mr_ordered"}]}: the project's open
    request lines for `items` on `source`, drafts first, newest first."""
    out = defaultdict(list)
    if not project or not items:
        return out
    if source == JOB_WORK:
        from pranera_planning.jobwork import request_lines
        for r in request_lines(project, items):
            out[r.item].append(dict(r))
        return out
    for r in frappe.db.sql(f"""SELECT mr.name mr, mr.docstatus, mri.name row, mri.item_code item,
            GREATEST(mri.stock_qty - mri.ordered_qty, 0) open, IFNULL(NULLIF(mri.conversion_factor, 0), 1) cf,
            (SELECT IFNULL(SUM(x.ordered_qty), 0) FROM `tabMaterial Request Item` x WHERE x.parent = mr.name) mr_ordered
            FROM `tabMaterial Request Item` mri
            JOIN `tabMaterial Request` mr ON mr.name = mri.parent AND mr.docstatus < 2
             AND mr.material_request_type = 'Manufacture'
             AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled', 'Ordered', 'Transferred', 'Issued', 'Received')
            WHERE {_proj_clause()} AND mri.item_code IN %(items)s
            ORDER BY mr.docstatus ASC, mr.creation DESC""", {"p": project, "items": tuple(items)}, as_dict=True):
        if flt(r.open) > EPS:
            out[r.item].append(dict(r))
    return out


def movable(project, items, source=MANUFACTURE):
    """{item: qty} that could be moved off `source`: open request quantity, drafts plus submitted
    requests with nothing ordered on them yet (no Work Order / no Purchase Order)."""
    return {i: round(sum(flt(l["open"]) for l in ls if l["docstatus"] == 0 or flt(l["mr_ordered"]) <= EPS), 3)
            for i, ls in open_lines(project, items, source).items()}


def plan_reductions(lines, qty):
    """Pure: [(mr, row, take)] taking qty from the lines in order (drafts first)."""
    out, left = [], float(qty or 0)
    for l in lines:
        if left <= EPS:
            break
        if l["docstatus"] == 1 and flt(l["mr_ordered"]) > EPS:
            continue
        take = min(left, flt(l["open"]))
        if take > EPS:
            out.append((l["mr"], l["row"], take))
            left -= take
    return out, max(0.0, left)


def reduce(project, item, qty, source=MANUFACTURE):
    """Take qty (stock units) of item off the project's `source` requests. Returns notes."""
    cuts, left = plan_reductions(open_lines(project, [item], source).get(item, []), qty)
    if left > EPS:
        if source == JOB_WORK:
            frappe.throw(_("Only {0} of {1} on the job-work requests can still be moved to in-house: the rest is "
                           "already on a Purchase Order. Reduce that Purchase Order instead.").format(flt(qty) - left, item))
        frappe.throw(_("Only {0} of {1} on the Manufacture requests can still be moved to job work: the rest is "
                       "already a Work Order. Reduce that Work Order instead.").format(flt(qty) - left, item))
    what = _("job-work request for {0}").format(item) if source == JOB_WORK else item
    by_mr = defaultdict(dict)
    for mr, row, take in cuts:
        by_mr[mr][row] = take
    notes = []
    for mr, rows in by_mr.items():
        doc = frappe.get_doc("Material Request", mr)
        if doc.docstatus == 0:
            _cut(doc, rows)
            if doc.get("items"):
                doc.save()
                notes.append(_("{0}: {1} reduced").format(mr, what))
            else:
                frappe.delete_doc("Material Request", mr)
                notes.append(_("{0}: deleted (nothing left)").format(mr))
        else:
            new = frappe.copy_doc(doc)
            new.amended_from = doc.name
            old_rows = [r.name for r in doc.get("items")]
            doc.cancel()
            _cut(new, {f"#{old_rows.index(k)}": v for k, v in rows.items()})
            if new.get("items"):
                new.insert()
                new.submit()
                notes.append(_("{0}: cancelled and amended as {1} with {2} reduced").format(mr, new.name, what))
            else:
                notes.append(_("{0}: cancelled (nothing left)").format(mr))
    return notes


def _cut(doc, rows):
    """Reduce lines by stock qty; rows keyed by line name, or '#i' for the i-th line of a copy."""
    keep = []
    for i, line in enumerate(doc.get("items") or []):
        take = rows.get(line.name) or rows.get(f"#{i}") or 0.0
        if take > EPS:
            cf = flt(line.conversion_factor) or 1.0
            stock = max(0.0, flt(line.stock_qty) - take)
            if stock <= EPS:
                continue
            line.stock_qty, line.qty = stock, stock / cf
        keep.append(line)
    doc.set("items", keep)
