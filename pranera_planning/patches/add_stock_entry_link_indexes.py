r"""Index every Link column that points to Stock Entry.

Cancelling a Stock Entry runs Frappe's check_no_back_links_exist, which looks for the entry in
every Link field whose target is Stock Entry, standard and custom. Most of those columns are
not indexed, so each look-up scans its table. On erptest one yarn-transfer cancel took 44.9 s,
33.1 s of it in that check:
  9.96 s Sales Invoice.stock_entry           6.98 s Stock Entry.outgoing_stock_entry
  5.61 s Stock Entry.custom_duplicate_stock_entry   3.92 s Stock Entry.source_stock_entry
  2.82 s Quotation.stock_entry               2.68 s Serial and Batch Bundle.custom_duplicate_stock_entry
  1.52 s Journal Entry Account.stock_entry   0.62 s Journal Entry.stock_entry
The fields are found from DocField and Custom Field, so links other apps add are covered too.
Indexes are built online and checked afterwards (see add_stock_project_indexes.add_online);
close any bench console before migrating.
"""
import frappe

from pranera_planning.patches.add_project_indexes import _indexed
from pranera_planning.patches.add_stock_project_indexes import add_online

TARGET = "Stock Entry"


def link_columns(target=TARGET):
    """[(doctype, fieldname)] of Link fields to `target` on real (non-single, non-virtual) tables."""
    rows = frappe.db.sql("""SELECT parent, fieldname FROM `tabDocField`
                            WHERE fieldtype = 'Link' AND options = %(t)s
                            UNION
                            SELECT dt, fieldname FROM `tabCustom Field`
                            WHERE fieldtype = 'Link' AND options = %(t)s""", {"t": target})
    out = []
    for doctype, field in rows:
        meta = frappe.db.get_value("DocType", doctype, ["issingle", "is_virtual"], as_dict=True)
        if not meta or meta.issingle or meta.get("is_virtual"):
            continue
        if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, field):
            out.append((doctype, field))
    return sorted(set(out))


def execute():
    for doctype, field in link_columns():
        if not _indexed(doctype, field):
            add_online(doctype, field)
