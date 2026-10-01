"""Project fields the Plan page uses: order type (made to stock / made to order), and for a
made-to-stock project the item family and period it was created for."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Project": [
            {"fieldname": "planning_order_type", "label": "Order type", "fieldtype": "Select",
             "options": "\nMade to stock\nMade to order", "insert_after": "project_type", "in_standard_filter": 1,
             "description": "Made to order: everything under this project belongs to its Sales Order. "
                            "Made to stock: free stock any order can reserve."},
            {"fieldname": "stock_family", "label": "Stock family", "fieldtype": "Data", "insert_after": "planning_order_type",
             "read_only": 1, "depends_on": "eval:doc.planning_order_type=='Made to stock'"},
            {"fieldname": "stock_period", "label": "Stock period", "fieldtype": "Data", "insert_after": "stock_family",
             "read_only": 1, "depends_on": "eval:doc.planning_order_type=='Made to stock'"},
        ],
    }, update=True)
