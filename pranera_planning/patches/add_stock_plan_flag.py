"""Material Request.from_stock_plan: set when a made-to-stock plan creates the request. Such a
request is meant to buy for stock, so the free-stock check records the free stock it found as a
comment instead of blocking it."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Material Request": [{
            "fieldname": "from_stock_plan", "label": "From a stock plan", "fieldtype": "Check",
            "insert_after": "reservation_override_reason", "read_only": 1, "no_copy": 1,
            "depends_on": "eval:doc.from_stock_plan",
            "description": "Created by a made-to-stock plan, which buys for stock on purpose: the free-stock "
                           "check notes the free stock on the request but doesn't block it.",
        }],
    }, update=True)
