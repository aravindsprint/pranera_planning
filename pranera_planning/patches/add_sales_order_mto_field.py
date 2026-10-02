"""Sales Order › Made to order: when ticked, submitting the order creates (or links) its
made-to-order project. Untouched orders — stock sales, Shopify, Unicommerce — are unaffected."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Sales Order": [{
            "fieldname": "made_to_order", "label": "Made to order", "fieldtype": "Check", "default": "0",
            "insert_after": "order_type", "allow_on_submit": 0, "in_standard_filter": 1,
            "description": "Tick when this order is made or bought for the customer. On submit it gets its own "
                           "made-to-order project (or the Project you choose), ready to plan in Project Planning.",
        }],
    }, update=True)
