r"""Index what Frappe scans when a stock entry is cancelled.

Profile of a 1 kg batch transfer cancel on erptest: 29.3 s, of which
  21.0 s  check_if_doc_is_dynamically_linked → get_dynamic_link_map → 148 ×
          "SELECT DISTINCT <type column> FROM <table>" — one for every Dynamic Link field on the
          site, run again in every request that cancels or deletes (the map is only kept for the
          request). A DISTINCT over an unindexed column reads the whole table; with an index it
          reads only the distinct values.
   4.2 s  check_if_doc_is_linked for the Serial and Batch Bundle the cancel cancels: every Link
          field to Serial and Batch Bundle is looked up.
The cancel runs these for the Stock Entry and again for each Serial and Batch Bundle.

This indexes (online, checked afterwards — see add_stock_project_indexes.add_online):
  * the type column of every Dynamic Link field (its `options`) on tables with ≥ MIN_ROWS rows;
  * every Link column to Serial and Batch Bundle;
and marks them search_index (Property Setter / Custom Field) so migrate keeps them (see
keep_planning_indexes). Close any bench console before migrating.
"""
import frappe

from pranera_planning.patches.add_project_indexes import _indexed
from pranera_planning.patches.add_stock_entry_link_indexes import link_columns
from pranera_planning.patches.add_stock_project_indexes import add_online
from pranera_planning.patches.keep_planning_indexes import mark_indexed

MIN_ROWS = 20000
INDEXABLE = ("varchar", "char", "int", "bigint", "date", "datetime")


def _real_table(doctype):
    meta = frappe.db.get_value("DocType", doctype, ["issingle", "is_virtual"], as_dict=True)
    return bool(meta) and not meta.issingle and not meta.get("is_virtual") and frappe.db.table_exists(doctype)


def _rows(doctype):
    r = frappe.db.sql("""SELECT TABLE_ROWS FROM information_schema.TABLES
                         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", f"tab{doctype}")
    return int(r[0][0] or 0) if r else 0


def _column_type(doctype, column):
    r = frappe.db.sql("""SELECT DATA_TYPE FROM information_schema.COLUMNS
                         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
                      (f"tab{doctype}", column))
    return (r[0][0] or "").lower() if r else ""


def dynamic_type_columns():
    """[(doctype, type column)] of every Dynamic Link field on a real table."""
    rows = frappe.db.sql("""SELECT parent, options FROM `tabDocField`
                            WHERE fieldtype = 'Dynamic Link' AND IFNULL(options, '') != ''
                            UNION
                            SELECT dt, options FROM `tabCustom Field`
                            WHERE fieldtype = 'Dynamic Link' AND IFNULL(options, '') != ''""")
    return sorted({(dt, col) for dt, col in rows
                   if _real_table(dt) and frappe.db.has_column(dt, col)})


def columns_to_index():
    out = [(dt, col) for dt, col in dynamic_type_columns() if _rows(dt) >= MIN_ROWS]
    out += link_columns("Serial and Batch Bundle")
    return sorted({(dt, col) for dt, col in out if _column_type(dt, col) in INDEXABLE})


def execute():
    cols = columns_to_index()
    for doctype, column in cols:
        try:
            mark_indexed(doctype, column)
            frappe.clear_cache(doctype=doctype)
        except Exception:
            frappe.log_error(title=f"search_index not set on {doctype}.{column}")
    frappe.db.commit()
    for doctype, column in cols:
        if _indexed(doctype, column):
            continue
        try:
            add_online(doctype, column)
        except Exception as e:
            print(f"WARNING: no index on `tab{doctype}`.`{column}`: {e}")
