r"""Index `project` on Stock Entry, Stock Entry Detail and Stock Ledger Entry.

Every Stock Entry with a project runs ERPNext's Project.set_consumed_material_cost on submit
and cancel, which sums Stock Entry Detail and Stock Ledger Entry rows by project. Without an
index those are full scans: on erptest one yarn transfer for project PORTAL/26/17 took 126 s
to submit (91 s in get_stock_entry_additional_costs, 20 s in get_stock_value_consumed), past
the web server's 120 s limit, so it rolled back. Same approach as add_project_indexes: only
where no index starts with the column; InnoDB adds them online, though on a large Stock
Ledger Entry table this migrate step can take a few minutes the first time.

By hand, from frappe-bench, with no bench console open (it would block the ALTER):
  nohup bench --site SITE mariadb -e "ALTER TABLE \`tabStock Entry Detail\` ADD INDEX
    \`project_planning_idx\` (\`project\`), ALGORITHM=INPLACE, LOCK=NONE" > /tmp/idx.log 2>&1 &"""
from pranera_planning.patches.add_project_indexes import _indexed
import frappe

COLUMNS = [
    ("Stock Entry", "project"),
    ("Stock Entry Detail", "project"),
    ("Stock Ledger Entry", "project"),
]


def execute():
    for doctype, column in COLUMNS:
        if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, column):
            continue
        if not _indexed(doctype, column):
            add_online(doctype, column)


def add_online(doctype, column):
    """Add the index without blocking writes, then check it is really there. On erptest the
    Stock Entry Detail index was missing after this patch had run (the other two were made),
    and a console session holding a transaction on the table blocked the manual ALTER: the
    ALTER waits for every open transaction on the table to end. Close bench consoles first."""
    frappe.db.commit()
    frappe.db.sql(f"ALTER TABLE `tab{doctype}` ADD INDEX `{column}_planning_idx` (`{column}`), "
                  "ALGORITHM=INPLACE, LOCK=NONE")
    if not _indexed(doctype, column):
        print(f"WARNING: the index on `tab{doctype}`.`{column}` was not created. Stock entries with a "
              f"project will stay slow; add it by hand (see pranera_planning/patches/add_stock_project_indexes.py).")
