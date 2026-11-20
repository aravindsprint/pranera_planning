"""Backport of ERPNext's faster Project.get_stock_entry_additional_costs.

ERPNext v15.124.5 (on erptest) sums Stock Entry Detail.additional_cost for a project in ONE
query: (line.project = P) OR (line.project blank AND entry.project = P). An OR across the two
joined tables can't use either table's `project` index, so it scans all of Stock Entry Detail
joined to Stock Entry: 85–90 s on erptest, on EVERY Stock Entry submit and cancel that has a
project (ERPNext calls it from update_project_consumed_material_cost). The web request times
out at 120 s, so transfers, manufacture entries and receipts for planned projects fail.

Later version-15 ERPNext splits it into two queries — lines carrying the project, and lines
with no project under an entry of the project — and adds them. The two sets can't overlap
(a line either has the project or is blank), so the total is the same; each half uses an
index (patch add_stock_project_indexes). This puts that version in place of the installed
one. Once ERPNext is updated past the change, this override does nothing different and can
be removed (see hooks.py).

Applied from before_request, before_job and a before_submit / before_cancel doc event on every
doctype: a module-level call in hooks.py alone is not enough, because Frappe caches hooks and
does not import hooks.py in every process (the first version of this override was missing
in the web workers and a bench console, and a manufacture entry still took 96 s).
"""
import frappe
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import flt


def get_stock_entry_additional_costs(self) -> float:
    stock_entry = frappe.qb.DocType("Stock Entry")
    item = frappe.qb.DocType("Stock Entry Detail")

    def total(condition):
        rows = (
            frappe.qb.from_(item)
            .join(stock_entry).on(stock_entry.name == item.parent)
            .select(Sum(item.additional_cost))
            .where((stock_entry.docstatus == 1) & (stock_entry.purpose != "Material Receipt") & condition)
        ).run()
        return flt(rows[0][0]) if rows else 0.0

    on_line = total(item.project == self.name)
    on_entry = total((IfNull(item.project, "") == "") & (stock_entry.project == self.name))
    return on_line + on_entry


def ensure(doc=None, method=None):
    """doc_events hook (before_submit / before_cancel on every doctype)."""
    apply()


def apply(*args, **kwargs):
    """Put the two-query version on ERPNext's Project class (idempotent)."""
    try:
        from erpnext.projects.doctype.project.project import Project
    except Exception:
        return
    if getattr(Project.get_stock_entry_additional_costs, "_pranera_split", False):
        return
    get_stock_entry_additional_costs._pranera_split = True
    Project.get_stock_entry_additional_costs = get_stock_entry_additional_costs
