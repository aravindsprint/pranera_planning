"""Workstation "Planning UOM": the unit a machine's output is counted in (Kgs for circular
knitting and dyeing, Pcs for flat knitting of collars and cuffs). The Workstation Board only
books an item on a machine whose Planning UOM is the item's stock UOM, so fabric in kg never
lands on a collar machine and collars in pieces never land on a circular one. The output field
keeps its fieldname kg_per_hour but is now labelled per hour in that unit."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Workstation": [
            {"fieldname": "kg_per_hour", "label": "Output per hour", "fieldtype": "Float", "insert_after": "planning_stage",
             "in_list_view": 1, "non_negative": 1,
             "description": "Output per hour per job, in the Planning UOM (kg for Kgs, pieces for Pcs). "
                            "Capacity a day = Output per hour × Working Hours × Production Capacity."},
            {"fieldname": "planning_uom", "label": "Planning UOM", "fieldtype": "Link", "options": "UOM",
             "insert_after": "kg_per_hour", "in_list_view": 1,
             "description": "The unit this machine's output is counted in. Only items stocked in this unit can be "
                            "booked on it (blank: any unit)."},
        ],
    }, update=True)
