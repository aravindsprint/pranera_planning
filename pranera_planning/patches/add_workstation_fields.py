"""Workstation fields for Time and Action allocation: the stage a machine works for, its output
in kg per hour, and for knitting machines their dia and gauge; on the Item, the knitting dia and
gauge it needs. Capacity also uses the Workstation's own Working Hours, Production Capacity and
Holiday List."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Workstation": [
            {"fieldname": "planning_section", "label": "Planning", "fieldtype": "Section Break", "insert_after": "description",
             "collapsible": 0},
            {"fieldname": "planning_stage", "label": "Planning stage", "fieldtype": "Data", "insert_after": "planning_section",
             "in_list_view": 1, "in_standard_filter": 1,
             "description": "The stage this machine works for, as named in Re-order Settings (Knitting, Dyeing, Stentering …)."},
            {"fieldname": "kg_per_hour", "label": "Kg per hour", "fieldtype": "Float", "insert_after": "planning_stage",
             "in_list_view": 1, "non_negative": 1,
             "description": "Output per hour per job. Capacity a day = Kg per hour × Working Hours × Production Capacity."},
            {"fieldname": "planning_cb", "fieldtype": "Column Break", "insert_after": "kg_per_hour"},
            {"fieldname": "machine_dia", "label": "Dia (inches)", "fieldtype": "Float", "insert_after": "planning_cb",
             "description": "Knitting machines: only items needing this dia can be booked on it."},
            {"fieldname": "machine_gauge", "label": "Gauge", "fieldtype": "Float", "insert_after": "machine_dia"},
        ],
        "Item": [
            {"fieldname": "knit_dia", "label": "Knitting dia (inches)", "fieldtype": "Float", "insert_after": "item_group",
             "description": "The machine dia this fabric is knitted on (Time and Action workstation check)."},
            {"fieldname": "knit_gauge", "label": "Knitting gauge", "fieldtype": "Float", "insert_after": "knit_dia"},
        ],
    }, update=True)
