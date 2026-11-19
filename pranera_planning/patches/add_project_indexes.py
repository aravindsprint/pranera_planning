"""Index the `project` column of the transaction tables the planning app filters by project.

ERPNext doesn't index them, so every project lookup (the overview's stage table, what's still
coming, produced batches) scanned the whole of Purchase Receipt Item, Material Request Item and
the rest: 11 s for an empty stock project on erptest. Existing indexes are left alone; InnoDB
adds these online, though on large tables migrate takes a little longer the first time."""
import frappe

COLUMNS = [
    ("Purchase Receipt Item", "project"),
    ("Purchase Order Item", "project"),
    ("Material Request Item", "project"),
    ("Material Request Item", "for_project"),           # only where a site added it
    ("Work Order", "project"),
    ("Subcontracting Order Item", "project"),
    ("Subcontracting Receipt Item", "project"),
]


def _indexed(doctype, column):
    """Whether some index already starts with `column`."""
    rows = frappe.db.sql(f"SHOW INDEX FROM `tab{doctype}` WHERE Column_name = %s AND Seq_in_index = 1", column)
    return bool(rows)


def execute():
    for doctype, column in COLUMNS:
        if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, column):
            continue
        if _indexed(doctype, column):
            continue
        frappe.db.add_index(doctype, [column], index_name=f"{column}_planning_idx")
