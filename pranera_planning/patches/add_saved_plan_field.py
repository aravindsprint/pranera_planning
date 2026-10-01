"""Project › Saved plan: the lines of the project's latest plan (JSON), written on Create.
A made-to-stock project's Overview reads its targets from it."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Project": [{"fieldname": "saved_plan", "label": "Saved plan", "fieldtype": "Long Text", "insert_after": "stock_period",
                     "read_only": 1, "hidden": 1, "no_copy": 1}],
    }, update=True)
