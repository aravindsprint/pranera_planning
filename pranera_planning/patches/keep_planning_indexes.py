"""Mark every column the planning patches index as "search index", so migrate keeps the index.

Frappe compares each table with its DocType when it updates the schema (on migrate, whenever a
field or custom field of that DocType changes) and drops the index of any column whose field is
not marked search_index (frappe/database/schema.py, DbColumn.build_for_alter_table). The indexes
added by add_project_indexes, add_stock_project_indexes and add_stock_entry_link_indexes were
plain SQL, so a later migrate removed them: on erptest Stock Entry Detail lost its `project`
index twice and every Stock Entry with a project went back to 90–190 s.

Standard fields get a Property Setter (search_index = 1, as Customize Form would set it); custom
fields get search_index ticked on the Custom Field. Then any missing index is created again.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from pranera_planning.patches.add_project_indexes import COLUMNS as PROJECT_COLUMNS, _indexed
from pranera_planning.patches.add_stock_entry_link_indexes import link_columns
from pranera_planning.patches.add_stock_project_indexes import COLUMNS as STOCK_COLUMNS, add_online


def planning_columns():
    cols = set(PROJECT_COLUMNS) | set(STOCK_COLUMNS) | set(link_columns())
    return sorted((dt, f) for dt, f in cols
                  if frappe.db.table_exists(dt) and frappe.db.has_column(dt, f))


def mark_indexed(doctype, fieldname):
    custom = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, ["name", "search_index"],
                                 as_dict=True)
    if custom:
        if not custom.search_index:
            frappe.db.set_value("Custom Field", custom.name, "search_index", 1, update_modified=False)
        return
    meta = frappe.get_meta(doctype)
    df = meta.get_field(fieldname)
    if df and not df.search_index:
        make_property_setter(doctype, fieldname, "search_index", 1, "Check", validate_fields_for_doctype=False)


def execute():
    for doctype, fieldname in planning_columns():
        mark_indexed(doctype, fieldname)
        frappe.clear_cache(doctype=doctype)
    frappe.db.commit()
    for doctype, fieldname in planning_columns():
        if not _indexed(doctype, fieldname):
            add_online(doctype, fieldname)
