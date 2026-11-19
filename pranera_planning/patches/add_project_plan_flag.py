"""Material Request.from_project_plan: set when a made-to-order plan (Project Planning) creates
the request. The plan reserves every lot it can before it asks to buy, so the free-stock check
measures such a request against that same reservable stock — not against stock with no project
or unnumbered rolls, which the plan cannot reserve and which used to block the plan's own request."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Material Request": [{
            "fieldname": "from_project_plan", "label": "From a project plan", "fieldtype": "Check",
            "insert_after": "from_stock_plan", "read_only": 1, "no_copy": 1,
            "depends_on": "eval:doc.from_project_plan",
            "description": "Created by a made-to-order plan after it reserved the stock it could: the free-stock "
                           "check only counts stock that plan could have reserved.",
        }],
    }, update=True)
